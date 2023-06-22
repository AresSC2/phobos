from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    DropCargo,
    KeepUnitSafe,
    PathUnitToTarget,
    PickUpCargo,
)
from ares.consts import WORKER_TYPES, UnitRole, UnitTreeQueryType
from ares.cython_extensions.units_utils import cy_center
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_unit import BaseUnit

if TYPE_CHECKING:
    from ares import AresBot

# when mines have 3 seconds of weapon cooldown left, medivac can drop off
THREE_SECONDS: int = int(22.4 * 3)


@dataclass
class MedivacMineDrops(BaseUnit):
    """Execute behavior for mines and medivac in a mine drop.

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator
        Used for getting information from managers in Ares.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator

    def execute(self, units: Units, **kwargs) -> None:
        """Execute the mine drop.

        Parameters
        ----------
        units : list[Unit]
            The units we want MedivacMineDrop to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        medivac_tag_to_mine_tracker : dict[int, dict]
            Tracker detailing medivac tag to mine tags.
            And target for the mine drop.

        """
        assert (
            "medivac_tag_to_mine_tracker" in kwargs
        ), "No value for medivac_tag_to_mine_tracker was passed into kwargs."
        # no units assigned to mine drop currently.
        if not units:
            return

        air_grid: np.ndarray = self.mediator.get_air_grid
        ground_grid: np.ndarray = self.mediator.get_ground_grid
        medivac_tag_to_mine_tracker: dict[int, dict] = kwargs[
            "medivac_tag_to_mine_tracker"
        ]

        # we have the exact units, but we need to split them depending on precise job.
        unit_role_dict: dict[UnitRole, set[int]] = self.mediator.get_unit_role_dict

        for medivac_tag, tracker_info in medivac_tag_to_mine_tracker.items():
            medivac: Optional[Unit] = self.ai.unit_tag_dict.get(medivac_tag, None)

            mines_to_pickup: list[Unit] = [
                u
                for u in units
                if u.tag in tracker_info["mine_tags"]
                and u.tag in unit_role_dict[UnitRole.DROP_UNITS_TO_LOAD]
            ]
            dropped_off_mines: list[Unit] = [
                u
                for u in units
                if u.tag in tracker_info["mine_tags"]
                and u.tag in unit_role_dict[UnitRole.DROP_UNITS_ATTACKING]
            ]

            if medivac and medivac_tag in unit_role_dict[UnitRole.DROP_SHIP]:
                self._handle_medivac_dropping_mines(
                    medivac, mines_to_pickup, air_grid, tracker_info["target"]
                )
            self._handle_mines_to_pickup(mines_to_pickup, medivac, ground_grid)
            self._handle_dropped_mines(ground_grid, dropped_off_mines, medivac)

    def _handle_medivac_dropping_mines(
        self,
        medivac: Unit,
        mines_to_pickup: list[Unit],
        air_grid: np.ndarray,
        target: Point2,
    ) -> None:
        """Control medivacs involvement.

        Parameters
        ----------
        medivac :
            The medivac to control.
        mines_to_pickup :
            The mines this medivac should carry.
        air_grid :
            Pathing grid this medivac can path on.
        target :
            Where should this medivac drop mines?
        """

        # can speed boost, do that and ignore other actions till next step
        if (
            medivac.is_moving
            and AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS in medivac.abilities
        ):
            medivac(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)
            return

        # recalculate precise target based on live game state
        target = self._calculate_precise_target(air_grid, medivac, target)

        # initiate a new mine drop maneuver
        mine_drop: CombatManeuver = CombatManeuver()

        # first priority is picking up units
        mine_drop.add(
            PickUpCargo(unit=medivac, grid=air_grid, pickup_targets=mines_to_pickup)
        )
        ready_to_drop: bool = self._can_drop_mines(medivac)
        # if ready to drop, add path to target and drop behaviors to `mine_drop`
        if ready_to_drop:
            # path to target
            mine_drop.add(
                PathUnitToTarget(
                    unit=medivac,
                    grid=air_grid,
                    target=target,
                    success_at_distance=4.0,
                )
            )
            # drop off the mines
            mine_drop.add(DropCargo(unit=medivac, target=medivac.position))
        # not ready to drop anything, add staying safe and path to dead-space
        else:
            mine_drop.add(KeepUnitSafe(unit=medivac, grid=air_grid))
            # TODO: Find dead space to hang around in for target here.
            #   This currently tries to move away from likely enemy position.
            safe_spot: Point2 = self.mediator.find_closest_safe_spot(
                from_pos=target.towards(self.mediator.get_enemy_nat, -20.0),
                grid=air_grid,
            )
            mine_drop.add(
                PathUnitToTarget(unit=medivac, grid=air_grid, target=safe_spot)
            )

        # register the behavior so it will be executed.
        self.ai.register_behavior(mine_drop)

    def _handle_mines_to_pickup(
        self, mines: list[Unit], medivac: Optional[Unit], ground_grid: np.ndarray
    ) -> None:
        """Control mines waiting rescue.

        TODO: If drilling claws upgrade available, don't rescue mines?

        Parameters
        ----------
        mines :
            Mines this method should control.
        medivac :
            Medivac that could possibly pick these mines up.
        ground_grid :
            Pathing grid these mines can path on.
        """
        for mine in mines:
            if mine.is_burrowed:
                mine(AbilityId.BURROWUP_WIDOWMINE)
            elif medivac:
                mine.move(medivac.position)
            else:
                self.mediator.assign_role(
                    tag=mine.tag, role=UnitRole.DROP_UNITS_ATTACKING
                )

    def _handle_dropped_mines(
        self, grid: np.ndarray, mines: list[Unit], medivac: Unit
    ) -> None:
        """Control mines that've recently been dropped off.

        Parameters
        ----------
        mines :
            Mines this method should control.
        """
        if len(mines) == 0:
            return
        # Use the ability tracker manager in Ares to check if weapon is ready.
        ability: AbilityId = AbilityId.WIDOWMINEATTACK_WIDOWMINEATTACK
        current_frame: int = self.ai.state.game_loop
        unit_to_ability_dict: dict[
            int, dict[AbilityId, int]
        ] = self.mediator.get_unit_to_ability_dict

        for mine in mines:
            attack_available: bool = (
                current_frame >= unit_to_ability_dict[mine.tag][ability]
            )
            if mine.is_burrowed and ability not in mine.abilities:
                attack_available = False
            if (attack_available or not medivac) and not mine.is_burrowed:
                mine(AbilityId.BURROWDOWN_WIDOWMINE)
            # if no medivac, just leave the mines alone
            elif ability not in mine.abilities and mine.is_burrowed and medivac:
                mine(AbilityId.BURROWUP_WIDOWMINE)
                # attack is not available, therefore:
                # - assign mine with role, so it can be rescued.
                # - tell ability tracker manager, so we know when weapon is ready.
                self.mediator.assign_role(
                    tag=mine.tag, role=UnitRole.DROP_UNITS_TO_LOAD
                )
                self.mediator.update_unit_to_ability_dict(
                    ability=ability,
                    unit_tag=mine.tag,
                )
            else:
                self.ai.register_behavior(KeepUnitSafe(mine, grid))

    def _can_drop_mines(self, medivac: Unit) -> bool:
        """Can this medivac drop off mines?

        Use the AbilityTrackerManager in ares to detect widowmines
        attack ability becoming available.

        Parameters
        ----------
        medivac :
            The medivac that is asking.

        Returns
        -------
        bool :
            Can we drop the mines?

        """
        if not medivac.has_cargo:
            return False

        cargo_tags: set[int] = medivac.passengers_tags
        current_frame: int = self.ai.state.game_loop
        unit_to_ability_dict: dict[
            int, dict[AbilityId, int]
        ] = self.mediator.get_unit_to_ability_dict

        for tag in cargo_tags:
            if tag in unit_to_ability_dict:
                attack_available: bool = current_frame >= (
                    unit_to_ability_dict[tag][AbilityId.WIDOWMINEATTACK_WIDOWMINEATTACK]
                    - THREE_SECONDS
                )
                if not attack_available:
                    return False

        return True

    def _calculate_precise_target(
        self, air_grid: np.ndarray, medivac: Unit, target: Point2
    ) -> Point2:
        """Given the precalculated target, update it depending on current game state.

        Parameters
        ----------
        air_grid :
            The grid the medivac is using for pathing and influence.
        medivac :
            The actual medivac to calculate drop target for.
        target :
            General precalculated target.

        Returns
        -------

        """
        med_pos: Point2 = medivac.position
        # look for a cluster of enemy workers nearby
        close_enemy_workers: list[Unit] = self.mediator.get_units_in_range(
            start_points=[med_pos],
            distances=[8.5],
            query_tree=UnitTreeQueryType.EnemyGround,
        )[0].filter(lambda u: u.type_id in WORKER_TYPES)

        if len(close_enemy_workers) >= 6:
            target = Point2(cy_center(close_enemy_workers))

        # current position is not safe for medivac, find a nearby safe spot
        if not self.mediator.is_position_safe(grid=air_grid, position=med_pos):
            target = self.mediator.find_closest_safe_spot(
                from_pos=target, grid=air_grid
            )

        return target
