from typing import Optional

from ares import AresBot, Hub, ManagerMediator
from ares.behaviors.mining import Mining
from ares.consts import DROP_ROLES, UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2

from bot.combat.base_unit import BaseUnit
from bot.combat.medivac_mine_drop import MedivacMineDrop
from bot.managers.drop_manager import DropManager
from bot.managers.orbital_manager import OrbitalManager


class MyBot(AresBot):
    # move these out of main at some point
    medivac_mine_drop: BaseUnit
    mine_drop_target: Point2

    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)

    async def on_start(self) -> None:
        await super(MyBot, self).on_start()
        # TODO: Somewhere else should handle initializing and executing
        #   combat classes? Left here for now as only this single class
        mine_drop_target = self.enemy_start_locations[0].towards(
            self.game_info.map_center, -4.0
        )
        self.medivac_mine_drop = MedivacMineDrop(
            self, self.config, self.mediator, mine_drop_target
        )

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)

        # TODO: Only pass in units specific to mine drops using DropManager
        self.medivac_mine_drop.execute(
            self.mediator.get_units_from_roles(roles=DROP_ROLES)
        )

        # for testing units get unassigned correctly, remove later
        for u in self.mediator.get_units_from_role(role=UnitRole.DEFENDING):
            u.move(self.mediator.get_own_nat)

        self.register_behavior(Mining())

        if iteration % 16 == 0:
            for depot in self.structures(UnitID.SUPPLYDEPOT):
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    async def register_managers(self) -> None:
        manager_mediator = ManagerMediator()
        drop_manager = DropManager(self, self.config, manager_mediator)
        orbital_manager = OrbitalManager(self, self.config, manager_mediator)
        self.manager_hub = Hub(
            self,
            self.config,
            manager_mediator,
            additional_managers=[drop_manager, orbital_manager],
        )

        await self.manager_hub.init_managers()

    # async def on_end(self, game_result: Result) -> None:
    #     await super(MyBot, self).on_end(game_result)
    #
    #     # custom on_end logic here ...
    #
    # async def on_building_construction_complete(self, unit: Unit) -> None:
    #     await super(MyBot, self).on_building_construction_complete(unit)
    #
    #     # custom on_building_construction_complete logic here ...
    #
    # async def on_unit_created(self, unit: Unit) -> None:
    #     await super(MyBot, self).on_unit_created(unit)
    #
    #     # custom on_unit_created logic here ...
    #

    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
    #     await super(MyBot, self).on_unit_took_damage(unit, amount_damage_taken)
    #
    #     # custom on_unit_took_damage logic here ...
