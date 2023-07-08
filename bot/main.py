from typing import Any, Optional

from ares import AresBot, Hub, ManagerMediator
from ares.behaviors.macro import Mining, SpawnController
from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit

from ares.cython_extensions.geometry import cy_distance_to
from bot.consts import NON_COMBAT_UNIT_TYPES
from bot.managers.combat_manager import CombatManager
from bot.managers.drop_manager import DropManager
from bot.managers.orbital_manager import OrbitalManager
from bot.managers.reaper_harass_manager import ReaperHarassManager
from bot.managers.scout_manager import ScoutManager
from bot.managers.worker_defence_manager import WorkerDefenceManager


class MyBot(AresBot):
    opening_build: str

    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)

        self.army_comp: dict[UnitID, Any] = {
            UnitID.MARINE: {"proportion": 0.8, "priority": 3},
            UnitID.MEDIVAC: {"proportion": 0.099, "priority": 2},
            UnitID.RAVEN: {"proportion": 0.001, "priority": 0},
            UnitID.SIEGETANK: {"proportion": 0.1, "priority": 1},
        }
        self.spawn_controller_active: bool = False

    async def on_start(self) -> None:
        await super(MyBot, self).on_start()

        self.opening_build = self.build_order_runner.chosen_opening

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)

        self.register_behavior(Mining())
        if self.spawn_controller_active:
            self.register_behavior(
                SpawnController(
                    army_composition_dict=self.army_comp,
                )
            )

        if iteration % 16 == 0:
            for depot in self.structures(UnitID.SUPPLYDEPOT):
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    async def register_managers(self) -> None:
        """
        Override the default `register_managers` in Ares, so we can
        add our own managers.
        """
        manager_mediator = ManagerMediator()

        self.manager_hub = Hub(
            self,
            self.config,
            manager_mediator,
            additional_managers=[
                CombatManager(self, self.config, manager_mediator),
                DropManager(self, self.config, manager_mediator),
                OrbitalManager(self, self.config, manager_mediator),
                ReaperHarassManager(self, self.config, manager_mediator),
                ScoutManager(self, self.config, manager_mediator),
                WorkerDefenceManager(self, self.config, manager_mediator),
            ],
        )

        await self.manager_hub.init_managers()

    async def on_unit_created(self, unit: Unit) -> None:
        await super(MyBot, self).on_unit_created(unit)

        # assign all units to ATTACKING role by default
        if unit.type_id not in NON_COMBAT_UNIT_TYPES:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.ATTACKING)

    async def on_building_construction_complete(self, unit: Unit) -> None:
        await super(MyBot, self).on_building_construction_complete(unit)

        if unit.type_id == UnitID.BARRACKSREACTOR and "OneOneOne" in self.opening_build:
            self.spawn_controller_active = True

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super(MyBot, self).on_unit_took_damage(unit, amount_damage_taken)

        compare_health: float = max(50.0, unit.health_max * 0.09)
        if unit.health < compare_health:
            unit(AbilityId.CANCEL_BUILDINPROGRESS)
            scvs: list[Unit] = [
                scv
                for scv in self.mediator.get_units_from_role(
                    role=UnitRole.BUILDING, unit_type=UnitID.SCV
                )
                if cy_distance_to(scv.position, unit.position) < 2.6
            ]
            for scv in scvs:
                self.mediator.assign_role(tag=scv.tag, role=UnitRole.GATHERING)
