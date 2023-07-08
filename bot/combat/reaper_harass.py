"""Behavior for harass Reaper."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

import numpy as np
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    KeepUnitSafe,
    PathUnitToTarget,
    StutterUnitBack,
    StutterUnitForward,
    UseAbility,
    AttackTarget,
)
from ares.consts import ALL_STRUCTURES, UnitTreeQueryType
from ares.cython_extensions.combat_utils import cy_pick_enemy_target, cy_is_facing
from ares.cython_extensions.geometry import cy_distance_to
from ares.cython_extensions.units_utils import cy_closest_to, cy_in_attack_range
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.behaviors.place_predictive_aoe import PlacePredictiveAoE
from bot.combat.base_unit import BaseUnit

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class ReaperHarass(BaseUnit):
    """Execute behavior for Reaper harass.

    Called from `ReaperHarassManager`

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
    reaper_grenade_range: float = 5.0

    def execute(self, units: Units, **kwargs) -> None:
        """Execute the Reaper harass.

        Parameters
        ----------
        units : list[Unit]
            The units we want MedivacMineDrop to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        reaper_to_target_tracker : Dict[int, Point2]
            Tracker detailing Reaper tag to enemy base.
        heal_threshold: float
            Health percentage where a Reaper should disengage to heal

        Returns
        -------

        """
        assert (
            "reaper_to_target_tracker" in kwargs
        ), "No value for reaper_to_target_tracker was passed into kwargs."
        assert (
            "heal_threshold" in kwargs
        ), "No value for heal_threshold was passed into kwargs."

        reaper_to_target_tracker: dict[int, Point2] = kwargs["reaper_to_target_tracker"]

        everything_near_reapers: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        proxy_pylons: list[Unit] = [
            s
            for s in self.ai.get_enemy_proxies(
                distance=85.0, from_position=self.ai.start_location
            )
            if s.type_id == UnitID.PYLON
        ]

        avoidance_grid = self.mediator.get_ground_avoidance_grid
        reaper_grid = self.mediator.get_climber_grid

        for unit in units:
            tag: int = unit.tag
            target: Point2 = reaper_to_target_tracker[tag]
            unit_pos: Point2 = unit.position

            pylons: Units = everything_near_reapers[tag].filter(
                lambda u: u.type_id == UnitID.PYLON
            )
            # get units near the reaper that can damage it
            threats_near_reaper: Units = everything_near_reapers[tag].filter(
                lambda u: u.can_attack_ground
                and u.type_id not in ALL_STRUCTURES
                and not u.is_memory
            )

            reaper_maneuver: CombatManeuver = CombatManeuver()
            # dodge biles, storms etc
            reaper_maneuver.add(KeepUnitSafe(unit=unit, grid=avoidance_grid))

            # reaper grenade
            if (
                len(threats_near_reaper) > 0
                and AbilityId.KD8CHARGE_KD8CHARGE in unit.abilities
            ):
                reaper_maneuver.add(
                    self._do_reaper_grenade(
                        reaper_grid, unit, unit_pos, target, threats_near_reaper
                    )
                )

            # send units home if they have low health or lack a target
            if (
                unit.health_percentage <= kwargs["heal_threshold"]
                or unit.tag not in reaper_to_target_tracker
            ):
                reaper_maneuver.add(self._send_reaper_to_heal(unit, reaper_grid))
                # register this maneuver and skip this iteration
                # as don't care about Behavior below if we reached here
                self.ai.register_behavior(reaper_maneuver)
                continue

            # no threats near reaper, get to target or handle proxy pylons
            if not threats_near_reaper:
                # proxy pylons
                if len(proxy_pylons) > 0 and pylons:
                    reaper_maneuver.add(
                        AttackTarget(unit, cy_closest_to(unit_pos, pylons))
                    )
                else:
                    reaper_maneuver.add(
                        PathUnitToTarget(unit=unit, grid=reaper_grid, target=target)
                    )

            # else threats are around
            else:
                reaper_maneuver.add(
                    self._reaper_harass_engagement(
                        reaper_grid=reaper_grid,
                        unit=unit,
                        target=target,
                        threats_near_reaper=threats_near_reaper,
                    )
                )

            self.ai.register_behavior(reaper_maneuver)

    def _do_reaper_grenade(
        self,
        reaper_grid: np.ndarray,
        unit: Unit,
        unit_pos: Point2,
        target: Point2,
        threats_near_reaper: Units,
    ) -> CombatManeuver:
        grenade_maneuver: CombatManeuver = CombatManeuver()
        close_unit: Unit = cy_closest_to(unit_pos, threats_near_reaper)
        # only throw grenades if the closest unit is visible
        if not close_unit.is_memory:
            facing: bool = close_unit.is_facing(unit)
            # close unit is not chasing reaper, throw aggressive grenade
            if facing:
                if path_to_target := self.mediator.find_raw_path(
                    start=unit_pos,
                    target=target,
                    grid=reaper_grid,
                    sensitivity=1,
                ):
                    grenade_maneuver.add(
                        PlacePredictiveAoE(
                            unit=unit,
                            path=path_to_target[:30],
                            enemy_center_unit=close_unit,
                            aoe_ability=AbilityId.KD8CHARGE_KD8CHARGE,
                            # TODO: verify, currently based on experimental evidence
                            ability_delay=34,
                        )
                    )
            elif (
                self.ai.is_visible(close_unit)
                and cy_distance_to(close_unit.position, unit.position)
                < self.reaper_grenade_range + close_unit.radius
            ):
                # TODO: Look for clumps etc a clump of workers
                grenade_maneuver.add(
                    UseAbility(
                        ability=AbilityId.KD8CHARGE_KD8CHARGE,
                        unit=unit,
                        target=close_unit.position,
                    )
                )

        return grenade_maneuver

    def _reaper_harass_engagement(
        self,
        reaper_grid: np.ndarray,
        unit: Unit,
        target: Point2,
        threats_near_reaper: Units,
    ) -> CombatManeuver:
        reaper_harass_maneuver: CombatManeuver = CombatManeuver()

        in_attack_range: list[Unit] = cy_in_attack_range(unit, threats_near_reaper)
        melee_units: Units = threats_near_reaper.filter(lambda u: u.ground_range < 3)
        light: Units = threats_near_reaper.filter(
            lambda u: u.is_light and not u.is_memory
        )
        only_melee: bool = len(melee_units) == len(threats_near_reaper)

        enemy_target: Optional[Unit] = None
        if melee_units:
            enemy_target = cy_pick_enemy_target(melee_units)
        # only light units around, pick a target
        elif len(light) == len(threats_near_reaper):
            enemy_target = cy_pick_enemy_target(light)

        if in_attack_range:
            closest_enemy: Unit = cy_closest_to(unit.position, threats_near_reaper)
            closest_enemy_dist: float = cy_distance_to(
                unit.position, closest_enemy.position
            )
            target_unit: Unit = cy_pick_enemy_target(in_attack_range)
            # enemy are a bit too close, run away
            if closest_enemy_dist < 2.5 and not unit.is_attacking:
                reaper_harass_maneuver.add(KeepUnitSafe(unit=unit, grid=reaper_grid))
            elif not only_melee or cy_is_facing(unit, enemy_target):
                reaper_harass_maneuver.add(
                    StutterUnitBack(
                        unit=unit,
                        target=target_unit,
                        kite_via_pathing=True,
                        # idea here is not to jump down cliff if kiting melee enemy
                        grid=reaper_grid
                        if not only_melee
                        else self.mediator.get_ground_grid,
                    )
                )
            else:
                reaper_harass_maneuver.add(
                    StutterUnitForward(unit=unit, target=target_unit)
                )

        elif enemy_target:
            # get in range of enemy target, at the safest possible cell
            # we out range the enemy so try to star in range
            if enemy_target.ground_range < unit.ground_range:
                radius: float = unit.ground_range + unit.radius + enemy_target.radius
            # else try to get out of the way
            else:
                radius: float = 10.0
            safest_spot: Point2 = self.mediator.find_closest_safe_spot(
                from_pos=enemy_target.position,
                grid=reaper_grid,
                radius=radius,
            )
            reaper_harass_maneuver.add(
                PathUnitToTarget(
                    unit=unit,
                    grid=reaper_grid,
                    target=safest_spot,
                    sensitivity=2,
                    sense_danger=False,
                )
            )

        else:
            reaper_harass_maneuver.add(
                PathUnitToTarget(
                    unit=unit,
                    grid=reaper_grid,
                    target=target,
                    sense_danger=False,
                )
            )

        return reaper_harass_maneuver

    def _send_reaper_to_heal(
        self,
        unit: Unit,
        reaper_grid: np.ndarray,
    ) -> CombatManeuver:
        """Create a CombatManeuver to get the Reaper to a healing spot.

        Arguments
        ---------
        unit : Unit
            The Reaper to keep safe.
        reaper_grid : np.ndarray
            Pathing grid to use for the Reaper.

        Returns
        -------
        CombatManeuver :
            Healing maneuver for this specific Reaper.

        """
        heal_maneuver: CombatManeuver = CombatManeuver()
        # best to run back home, keeping unit safe can make reaper
        # sit at bottom of cliffs and die from high ground enemies'
        # Reaper will likely turn around as healing starts
        heal_maneuver.add(
            PathUnitToTarget(
                unit=unit,
                grid=reaper_grid,
                target=self.ai.start_location,
            )
        )

        return heal_maneuver
