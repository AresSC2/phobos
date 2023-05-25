from typing import Optional

from sc2.ids.ability_id import AbilityId

from ares import AresBot, Hub, ManagerMediator
from ares.behaviors.mining import Mining

from sc2.ids.unit_typeid import UnitTypeId as UnitID

from bot.managers.orbital_manager import OrbitalManager


class MyBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)

        self.register_behavior(Mining())

        if iteration % 16 == 0:
            for depot in self.structures(UnitID.SUPPLYDEPOT):
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    """
    Can use `python-sc2` hooks as usual, but make a call the inherited method in the superclass
    Examples:
    """

    async def register_managers(self) -> None:
        manager_mediator = ManagerMediator()
        orbital_manager = OrbitalManager(self, self.config, manager_mediator)
        self.manager_hub = Hub(
            self,
            self.config,
            manager_mediator,
            additional_managers=[orbital_manager],
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
    # async def on_unit_destroyed(self, unit_tag: int) -> None:
    #     await super(MyBot, self).on_unit_destroyed(unit_tag)
    #
    #     # custom on_unit_destroyed logic here ...
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
    #     await super(MyBot, self).on_unit_took_damage(unit, amount_damage_taken)
    #
    #     # custom on_unit_took_damage logic here ...
