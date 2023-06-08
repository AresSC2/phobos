"""Behavior for harass Reaper."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Union

import numpy as np

from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    KeepUnitSafe,
    PathUnitToTarget,
)
from ares.consts import UnitTreeQueryType
from ares.cython_extensions.units_utils import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.behaviors.a_move import AMove
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

        reaper_to_target_tracker: Dict[int, Point2] = kwargs["reaper_to_target_tracker"]

        everything_near_reapers: Dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )

        reaper_grid = self.mediator.get_climber_grid

        for unit in units:
            # get units near the reaper that can damage it
            threats_near_reaper: Units = everything_near_reapers[unit.tag].filter(
                lambda u: u.can_attack_ground
            )

            # send units home if they have low health or lack a target
            if (
                unit.health_percentage <= kwargs["heal_threshold"]
                or unit.tag not in reaper_to_target_tracker
            ):
                self.ai.register_behavior(
                    self._send_reaper_to_heal(unit, threats_near_reaper, reaper_grid)
                )
                continue

            reaper_maneuver = CombatManeuver()

            # default to keeping the reaper safe via movement
            reaper_maneuver.add(KeepUnitSafe(unit=unit, grid=reaper_grid))

            if not threats_near_reaper:
                # nothing nearby, head to the target
                reaper_maneuver.add(
                    AMove(unit=unit, target=reaper_to_target_tracker[unit.tag])
                )
            else:
                close_unit = cy_closest_to(unit.position, threats_near_reaper)
                # only throw grenades if the closest unit is visible
                if close_unit.is_visible:
                    # get path to target for predictive AoE
                    if path_to_target := self.mediator.find_raw_path(
                        start=unit.position,
                        target=reaper_to_target_tracker[unit.tag],
                        grid=reaper_grid,
                        sensitivity=1,
                    ):
                        reaper_maneuver.add(
                            PlacePredictiveAoE(
                                unit=unit,
                                path=path_to_target[:30],
                                enemy_center_unit=close_unit,
                                aoe_ability=AbilityId.KD8CHARGE_KD8CHARGE,
                                # TODO: verify, currently based on experimental evidence
                                ability_delay=34,
                            )
                        )
                    # attack the close unit in case the grenade doesn't execute
                    reaper_maneuver.add(AMove(unit=unit, target=close_unit))

            # head towards the target if nothing else executes
            reaper_maneuver.add(
                AMove(unit=unit, target=reaper_to_target_tracker[unit.tag])
            )
            self.ai.register_behavior(reaper_maneuver)

    def _send_reaper_to_heal(
        self,
        unit: Unit,
        nearby_enemy: Union[List[Unit], Units],
        reaper_grid: np.ndarray,
    ) -> CombatManeuver:
        """Create a CombatManeuver to get the Reaper to a healing spot.

        Arguments
        ---------
        unit : Unit
            The Reaper to keep safe.
        nearby_enemy : Units
            Enemy units that are nearby.
        reaper_grid : np.ndarray
            Pathing grid to use for the Reaper.

        Returns
        -------
        CombatManeuver :
            Healing maneuver for this specific Reaper.

        """
        heal_maneuver: CombatManeuver = CombatManeuver()
        # keep the unit safe
        heal_maneuver.add(KeepUnitSafe(unit=unit, grid=reaper_grid))

        # run home if there's anything nearby
        if nearby_enemy:
            heal_maneuver.add(
                PathUnitToTarget(
                    unit=unit,
                    grid=reaper_grid,
                    target=self.mediator.get_rally_point,
                )
            )

        return heal_maneuver
