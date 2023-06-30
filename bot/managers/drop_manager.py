from typing import TYPE_CHECKING, Callable

from sc2.position import Point2

from ares import ManagerMediator
from ares.consts import DROP_ROLES, UnitRole
from ares.cython_extensions.geometry import cy_towards
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_unit import BaseUnit
from bot.combat.medivac_mine_drops import MedivacMineDrops

if TYPE_CHECKING:
    from ares import AresBot


class DropManager(Manager):
    # at this percentage, medivac should be unassigned and go home
    MIN_HEALTH_MEDIVAC_PERC: float = 0.2

    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle all drop related logic.

        This manager should assign units to drop, and call
        relevant drop related combat classes to execute all
        drops.

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

        self._assigned_111_mine_drop: bool = False
        # {med_tag : {"mine_tags: {12, 32, 55}, "target": Point2((50.0, 75.5)}}
        self._medivac_tag_to_mine_tracker: dict[int, dict] = dict()

        self._mine_drops: BaseUnit = MedivacMineDrops(ai, config, mediator)

    async def update(self, iteration: int) -> None:
        self._assign_mine_drops()
        self._unassign_drops()
        self._execute_drops()

    def _assign_mine_drops(self) -> None:
        if (
            self.ai.build_order_runner.chosen_opening == "OneOneOne"
            and not self._assigned_111_mine_drop
            and not self.manager_mediator.get_main_ground_threats_near_townhall
        ):
            mine_drop_target: Point2 = Point2(
                cy_towards(
                    self.ai.enemy_start_locations[0], self.ai.game_info.map_center, -4.0
                )
            )
            unit_dict: dict[UnitID, Units] = self.manager_mediator.get_own_army_dict

            if UnitID.MEDIVAC in unit_dict and (
                UnitID.WIDOWMINE in unit_dict or UnitID.WIDOWMINEBURROWED in unit_dict
            ):
                medivacs: Units = unit_dict[UnitID.MEDIVAC].filter(
                    lambda m: m.health_percentage > self.MIN_HEALTH_MEDIVAC_PERC
                )
                mines: Units = self.ai.units(
                    {UnitID.WIDOWMINE, UnitID.WIDOWMINEBURROWED}
                )

                if len(medivacs) > 0 and len(mines) > 1:
                    assign_role: Callable = self.manager_mediator.assign_role
                    medivac: Unit = unit_dict[UnitID.MEDIVAC][0]
                    assign_role(tag=medivac.tag, role=UnitRole.DROP_SHIP)
                    for u in mines:
                        assign_role(tag=u.tag, role=UnitRole.DROP_UNITS_TO_LOAD)
                    self._medivac_tag_to_mine_tracker[medivac.tag] = {
                        "mine_tags": {mine.tag for mine in mines},
                        "target": mine_drop_target,
                    }
                    self._assigned_111_mine_drop = True

    def _unassign_drops(self) -> None:
        self._unassign_mine_drops(switch_to=UnitRole.ATTACKING)

    def _execute_drops(self) -> None:
        self._mine_drops.execute(
            self.manager_mediator.get_units_from_roles(roles=DROP_ROLES),
            medivac_tag_to_mine_tracker=self._medivac_tag_to_mine_tracker,
        )

    def _unassign_mine_drops(self, switch_to: UnitRole) -> None:
        # unassign units from mine drop if medivac or assigned mines have died
        for med_tag, mine_tracker in self._medivac_tag_to_mine_tracker.items():
            if medivac := self.ai.unit_tag_dict.get(med_tag, None):
                # deal with low health medivac, assign mines to drop attack
                if medivac.health_percentage <= self.MIN_HEALTH_MEDIVAC_PERC:
                    self.manager_mediator.assign_role(tag=medivac.tag, role=switch_to)
                    self.manager_mediator.batch_assign_role(
                        tags=mine_tracker["mine_tags"],
                        role=UnitRole.DROP_UNITS_ATTACKING,
                    )
                else:
                    # all looking good, leave alone
                    if medivac.has_cargo:
                        return
                    # no cargo, are mines still around?
                    else:
                        mines: list[Unit] = [
                            m
                            for m in self.ai.units
                            if m.tag in mine_tracker["mine_tags"]
                        ]
                        # no mines, assign medivac to something else
                        if len(mines) == 0:
                            self.manager_mediator.assign_role(
                                tag=medivac.tag, role=switch_to
                            )
            # no medivac exists, ensure mines are left on attacking mode
            else:
                self.manager_mediator.batch_assign_role(
                    tags=mine_tracker["mine_tags"], role=UnitRole.DROP_UNITS_ATTACKING
                )
