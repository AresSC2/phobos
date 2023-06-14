from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.consts import UnitRole, UnitTreeQueryType
from ares.cython_extensions.geometry import cy_distance_to
from ares.managers.manager import Manager
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.units import Units

if TYPE_CHECKING:
    from ares import AresBot


class CombatManager(Manager):
    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle all main combat logic.

        This manager is incharge of all the main offensive
        or defensive units. Combat classes should be called
        as needed to execute unit control.

        See DropManager for drop assignment and execution.

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

    @property
    def rally_point(self) -> Point2:
        return self.manager_mediator.get_own_nat.towards(
            self.ai.game_info.map_center, 8.0
        )

    async def update(self, iteration: int) -> None:
        # only basic goto rally point logic for now
        # this should all go in combat classes eventually
        defenders: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.DEFENDING
        )
        close_to_rally: Units = self.manager_mediator.get_units_in_range(
            start_points=[self.rally_point],
            distances=9.5,
            query_tree=UnitTreeQueryType.AllOwn,
        )[0]
        close_to_rally_tags: set[int] = {u.tag for u in close_to_rally}
        _rally_point: Point2 = self.rally_point

        for u in defenders:
            if u.tag not in close_to_rally_tags:
                u.move(_rally_point)
            elif (
                u.type_id == UnitID.WIDOWMINE
                and cy_distance_to(u.position, _rally_point) < 6.0
            ):
                u(AbilityId.BURROWDOWN_WIDOWMINE)
            elif (
                u.type_id == UnitID.SIEGETANK
                and cy_distance_to(u.position, _rally_point) < 6.0
            ):
                u(AbilityId.SIEGEMODE_SIEGEMODE)
