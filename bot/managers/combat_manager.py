from itertools import cycle
from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.behaviors.combat.individual import DropCargo, StutterUnitBack
from ares.consts import UnitRole, UnitTreeQueryType
from ares.cython_extensions.geometry import cy_distance_to
from ares.cython_extensions.units_utils import cy_closest_to
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
        self.expansions_generator = None
        self.current_base_target: Point2 = self.ai.enemy_start_locations[0]

    @property
    def attack_target(self) -> Point2:
        """ Quick attack target implementation, improve this later. """
        if self.ai.enemy_structures:
            return self.ai.enemy_structures.closest_to(self.ai.start_location).position
        else:
            # cycle through base locations
            if self.ai.is_visible(self.current_base_target):
                if not self.expansions_generator:
                    base_locations: list[Point2] = [
                        i for i in self.ai.expansion_locations_list
                    ]
                    self.expansions_generator = cycle(base_locations)

                self.current_base_target = next(self.expansions_generator)

            return self.current_base_target

    async def update(self, iteration: int) -> None:
        """ At the moment not much more than an a-move for main force.

        Parameters
        ----------
        iteration
        """
        attackers: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.ATTACKING
        )

        # everything we have no logic for yet gets a-moved
        # this should all go in combat classes eventually
        target: Point2 = self.attack_target

        ground, flying = self.ai.split_ground_fliers(attackers)

        for u in ground:
            # mines burrow and wait for mine drop for now
            if u.type_id == UnitID.WIDOWMINE:
                u(AbilityId.BURROWDOWN_WIDOWMINE)
            else:
                if u.is_flying:
                    # unload any medivacs
                    if u.has_cargo and self.ai.in_pathing_grid(u.position):
                        self.ai.register_behavior(DropCargo(unit=u, target=u.position))
                    else:
                        u.attack(cy_closest_to(target, attackers).position)
                else:
                    u.attack(target)

        for u in flying:
            if u.has_cargo and self.ai.in_pathing_grid(u.position):
                self.ai.register_behavior(DropCargo(unit=u, target=u.position))

            elif ground:
                u.attack(cy_closest_to(target, ground).position)
