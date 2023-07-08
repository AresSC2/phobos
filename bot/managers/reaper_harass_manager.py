"""Handle Reaper Harass."""
from typing import TYPE_CHECKING, Dict, Set

from sc2.data import Race
from sc2.unit import Unit

from ares import ManagerMediator
from ares.consts import UnitRole, UnitTreeQueryType
from ares.cython_extensions.units_utils import cy_closest_to
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2

from bot.combat.base_unit import BaseUnit
from bot.combat.reaper_harass import ReaperHarass

if TYPE_CHECKING:
    from ares import AresBot


class ReaperHarassManager(Manager):
    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle all Reaper harass.

        This manager should assign Reapers to harass and call
        relevant combat classes to execute the harass.

        Parameters
        ----------
        ai :
            Bot object that will be running the game
        config :
            Dictionary with the data from the configuration file
        mediator :
            ManagerMediator used for getting information from other managers.
        """
        super().__init__(ai, config, mediator)

        self._assigned_reaper_harass: bool = False
        self._reaper_to_target_tracker: dict[int, Point2] = dict()

        self._reaper_harass: BaseUnit = ReaperHarass(ai, config, mediator)
        self.healing_reaper_tags: Set[int] = set()
        self.reaper_attack_threshold: float = 0.9
        self.reaper_retreat_threshold: float = 0.45

        # TODO: make the target more sophisticated
        self.reaper_harass_target: Point2 = ai.enemy_start_locations[0]

    async def update(self, iteration: int) -> None:
        self._assign_reaper_harass()
        self._unassign_harass()
        self._execute_harass()

    def _assign_reaper_harass(self) -> None:
        if reapers := self.manager_mediator.get_own_army_dict.get(UnitID.REAPER, None):
            self.manager_mediator.batch_assign_role(
                tags=reapers.tags, role=UnitRole.HARASSING
            )

            self._reaper_to_target_tracker: Dict[int, Point2] = {}
            for reaper in reapers:
                # remove healed reapers from healing tracking
                if (
                    reaper.tag in self.healing_reaper_tags
                    and reaper.health_percentage >= self.reaper_attack_threshold
                ):
                    self.healing_reaper_tags.remove(reaper.tag)

                # add low health reapers to healing tracking
                if reaper.health_percentage < self.reaper_retreat_threshold:
                    self.healing_reaper_tags.add(reaper.tag)

                # assign the reaper a target
                target: Point2 = self.reaper_harass_target
                if (
                    self.ai.enemy_race == Race.Zerg
                    and self.manager_mediator.get_main_ground_threats_near_townhall
                ):
                    target = self.ai.main_base_ramp.top_center

                self._reaper_to_target_tracker[reaper.tag] = target

    def _unassign_harass(self) -> None:
        # TODO: do something
        pass

    def _execute_harass(self) -> None:
        if reapers := self.manager_mediator.get_units_from_role(
            role=UnitRole.HARASSING, unit_type=UnitID.REAPER
        ):
            self._reaper_harass.execute(
                reapers,
                reaper_to_target_tracker=self._reaper_to_target_tracker,
                heal_threshold=self.reaper_retreat_threshold,
            )
