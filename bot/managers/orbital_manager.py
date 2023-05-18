from typing import TYPE_CHECKING

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

from ares import ManagerMediator
from ares.managers.manager import Manager

if TYPE_CHECKING:
    from ares import AresBot


class OrbitalManager(Manager):
    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Set up the manager.

        Parameters
        ----------
        ai :
            Bot object that will be running the game
        config :
            Dictionary with the data from the configuration file
        mediator :
            ManagerMediator used for getting information from other managers.

        Returns
        -------

        """
        super().__init__(ai, config, mediator)

    async def update(self, iteration: int) -> None:
        """
        Basic mule logic till this can be improved.
        """
        oc_id: UnitID = UnitID.ORBITALCOMMAND
        structures_dict: dict[UnitID, Units] = self.manager_mediator.get_own_structures_dict
        if oc_id not in structures_dict:
            return

        for oc in structures_dict[oc_id].filter(lambda x: x.energy >= 50):
            mfs: Units = self.ai.mineral_field.closer_than(10, oc)
            if mfs:
                mf: Unit = max(mfs, key=lambda x: x.mineral_contents)
                oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mf)
