"""Behavior for harass Reaper."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

import numpy as np
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    KeepUnitSafe,
    PathUnitToTarget,
    StutterUnitBack,
    UseAbility,
)
from ares.consts import ALL_STRUCTURES, WORKER_TYPES, UnitTreeQueryType
from ares.cython_extensions.combat_utils import cy_pick_enemy_target
from ares.cython_extensions.geometry import cy_distance_to
from ares.cython_extensions.units_utils import cy_closest_to, cy_in_attack_range
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.ability_id import AbilityId
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

        avoidance_grid = self.mediator.get_ground_avoidance_grid
        reaper_grid = self.mediator.get_climber_grid

        for unit in units:
            target: Point2 = reaper_to_target_tracker[unit.tag]
            unit_pos: Point2 = unit.position
            distance_to_target: float = cy_distance_to(unit_pos, target)
            close_to_target: bool = distance_to_target < 15.0
            # get units near the reaper that can damage it
            threats_near_reaper: Units = everything_near_reapers[unit.tag].filter(
                lambda u: u.can_attack_ground and u.type_id not in ALL_STRUCTURES
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

            # no threats near reaper, get to target
            if not threats_near_reaper:
                reaper_maneuver.add(
                    PathUnitToTarget(
                        unit=unit,
                        grid=reaper_grid,
                        target=target,
                        success_at_distance=4.0,
                        # already know there are no threats
                        sense_danger=False,
                    )
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
            # close unit is not chasing reaper, throw aggressive grenade
            # TODO: Look for clumps etc a clump of workers
            if not close_unit.is_facing(unit):
                grenade_maneuver.add(
                    UseAbility(
                        ability=AbilityId.KD8CHARGE_KD8CHARGE,
                        unit=unit,
                        target=close_unit.position,
                    )
                )
            # get path to target for predictive AoE
            elif path_to_target := self.mediator.find_raw_path(
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
        enemy_workers: Units = threats_near_reaper.filter(
            lambda u: u.type_id in WORKER_TYPES
        )
        light: Units = threats_near_reaper.filter(
            lambda u: u.is_light and not u.is_memory
        )

        enemy_target: Optional[Unit] = None
        if enemy_workers and self.mediator.is_position_safe(
            grid=reaper_grid, position=unit.position
        ):
            enemy_target = cy_pick_enemy_target(enemy_workers)
        # only light units around, pick a target
        elif len(light) == len(threats_near_reaper):
            enemy_target = cy_pick_enemy_target(light)

        if in_attack_range:
            reaper_harass_maneuver.add(
                StutterUnitBack(
                    unit=unit,
                    target=cy_pick_enemy_target(in_attack_range),
                    kite_via_pathing=True,
                    grid=reaper_grid,
                )
            )

        elif enemy_target:
            # get in range of enemy target, at the safest possible cell
            safest_spot: Point2 = self.mediator.find_closest_safe_spot(
                from_pos=enemy_target.position,
                grid=reaper_grid,
                radius=5.0 + enemy_target.radius + unit.radius,
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
                target=self.mediator.get_rally_point,
            )
        )

        return heal_maneuver
