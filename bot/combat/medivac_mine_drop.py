from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    DropCargo,
    KeepUnitSafe,
    PathUnitToTarget,
    PickUpCargo,
)
from ares.consts import UnitRole
from ares.cython_extensions.units_utils import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_unit import BaseUnit

if TYPE_CHECKING:
    from ares import AresBot

# when mines have 4 seconds of weapon cooldown left, medivac can drop off
FOUR_SECONDS: int = int(22.5 * 4)


@dataclass
class MedivacMineDrop(BaseUnit):
    """Execute behavior for mines and medivac in a mine drop.

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator
        Used for getting information from managers in Ares.
    target : Point2
        Where mines should be dropped off.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator
    target: Point2

    def execute(self, units: Units) -> None:
        """Execute the mine drop.

        Parameters
        ----------
        units : list[Unit]
            The units we want MedivacMineDrop to control.

        """

        # we have the exact units, but we need to split them depending on precise job.
        unit_role_dict: dict[UnitRole, set[int]] = self.mediator.get_unit_role_dict

        medivacs: list[Unit] = [
            u for u in units if u.tag in unit_role_dict[UnitRole.DROP_SHIP]
        ]
        mines_to_pickup: list[Unit] = [
            u for u in units if u.tag in unit_role_dict[UnitRole.DROP_UNITS_TO_LOAD]
        ]
        dropped_off_mines: list[Unit] = [
            u for u in units if u.tag in unit_role_dict[UnitRole.DROP_UNITS_ATTACKING]
        ]

        air_grid: np.ndarray = self.mediator.get_air_grid
        ground_grid: np.ndarray = self.mediator.get_ground_grid

        self._handle_medivacs_dropping_mines(medivacs, mines_to_pickup, air_grid)
        self._handle_mines_to_pickup(mines_to_pickup, medivacs, ground_grid)
        self._handle_dropped_mines(dropped_off_mines)

    def _handle_medivacs_dropping_mines(
        self, medivacs: list[Unit], mines_to_pickup: list[Unit], air_grid: np.ndarray
    ) -> None:
        """Control medivacs involvement.

        Parameters
        ----------
        medivacs :
            The medivacs to control.
        mines_to_pickup :
            The mines this medivac should carry.
        air_grid :
            Pathing grid this medivac can path on.
        """
        for medivac in medivacs:
            # can speed boost, do that and ignore other actions till next step
            if (
                medivac.is_moving
                and AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS in medivac.abilities
            ):
                medivac(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)
                continue

            # initiate a new mine drop maneuver
            mine_drop: CombatManeuver = CombatManeuver()

            # first priority is picking up units
            mine_drop.add(
                PickUpCargo(unit=medivac, grid=air_grid, pickup_targets=mines_to_pickup)
            )
            ready_to_drop: bool = self._can_drop_mines(medivac)
            # if ready to drop, add path to target and drop behaviors to `mine_drop`
            if ready_to_drop:
                # path
                mine_drop.add(
                    PathUnitToTarget(
                        unit=medivac,
                        grid=air_grid,
                        target=self.target,
                        success_at_distance=1.5,
                    )
                )
                # drop off the mines
                mine_drop.add(DropCargo(unit=medivac, target=medivac.position))
            # not ready to drop anything, add staying safe and path to deadspace
            # to `mine_drop` maneuver
            else:
                mine_drop.add(KeepUnitSafe(unit=medivac, grid=air_grid))
                mine_drop.add(
                    PathUnitToTarget(
                        unit=medivac,
                        grid=air_grid,
                        # TODO: Find dead space to hang around in for target here.
                        #   This currently tries to move away from likely enemy position.
                        target=self.target.towards(self.mediator.get_enemy_nat, -15.0),
                        success_at_distance=3.0,
                    )
                )

            # register the behavior so it will be executed.
            self.ai.register_behavior(mine_drop)

    def _handle_mines_to_pickup(
        self, mines: list[Unit], medivacs: list[Unit], ground_grid: np.ndarray
    ) -> None:
        """Control mines waiting rescue.

        Parameters
        ----------
        mines :
            Mines this method should control.
        medivacs :
            Medivacs that could possibly pick these mines up.
        ground_grid :
            Pathing grid these mines can path on.
        """
        for mine in mines:
            if medivacs:
                mine.move(cy_closest_to(mine.position, medivacs))
            else:
                self.ai.register_behavior(KeepUnitSafe(unit=mine, grid=ground_grid))

    def _handle_dropped_mines(self, mines: list[Unit]) -> None:
        """Control mines that've recently been dropped off.

        Parameters
        ----------
        mines :
            Mines this method should control.
        """

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
            if attack_available and not mine.is_burrowed:
                mine(AbilityId.BURROWDOWN_WIDOWMINE)
            elif not attack_available and mine.is_burrowed:
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

    def _can_drop_mines(self, medivac: Unit) -> bool:
        """ Can this medivac drop off mines?

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
                    - FOUR_SECONDS
                )
                if not attack_available:
                    return False

        return True
