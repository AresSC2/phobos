from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.consts import UnitRole
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

if TYPE_CHECKING:
    from ares import AresBot


class DropManager(Manager):
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

        self.__assigned_111_mine_drop: bool = False
        self.medivac_tag_to_mine_tags: dict[int, set[int]] = dict()

    async def update(self, iteration: int) -> None:
        """
        Basic mule logic till this can be improved.
        """
        self._assign_mine_drops()

        self._unassign_drops()

    def _assign_mine_drops(self) -> None:
        if (
            self.ai.build_order_runner.chosen_opening == "OneOneOne"
            and not self.__assigned_111_mine_drop
        ):
            unit_dict: dict[UnitID, Units] = self.manager_mediator.get_own_army_dict
            if UnitID.MEDIVAC in unit_dict and UnitID.WIDOWMINE in unit_dict:
                medivacs: Units = unit_dict[UnitID.MEDIVAC]
                mines: Units = unit_dict[UnitID.WIDOWMINE]
                if len(medivacs) > 0 and len(mines) > 1:
                    medivac: Unit = unit_dict[UnitID.MEDIVAC][0]
                    self.manager_mediator.assign_role(
                        tag=medivac.tag, role=UnitRole.DROP_SHIP
                    )
                    for u in mines:
                        self.manager_mediator.assign_role(
                            tag=u.tag, role=UnitRole.DROP_UNITS_TO_LOAD
                        )
                    self.medivac_tag_to_mine_tags[medivac.tag] = {
                        mine.tag for mine in mines
                    }

    def _unassign_drops(self) -> None:
        # unassign units from mine drop if medivac or assigned mines have died
        for med_tag, mine_tags in self.medivac_tag_to_mine_tags.items():
            if medivac := self.ai.unit_tag_dict.get(med_tag, None):
                if medivac.has_cargo:
                    return
                else:
                    if len([m for m in self.ai.units if m.tag in mine_tags]) == 0:
                        self.manager_mediator.assign_role(
                            tag=medivac.tag, role=UnitRole.DEFENDING
                        )
            # no medivac, reassign mines
            else:
                self.manager_mediator.batch_assign_role(
                    tags=mine_tags, role=UnitRole.DEFENDING
                )
