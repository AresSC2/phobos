from typing import TYPE_CHECKING

from sc2.data import Race
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ares import ManagerMediator
from ares.consts import UnitRole, UnitTreeQueryType, WORKER_TYPES
from ares.cython_extensions.geometry import cy_distance_to
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID


from bot.combat.base_unit import BaseUnit
from bot.combat.worker_scouts import WorkerScouts

if TYPE_CHECKING:
    from ares import AresBot


class ScoutManager(Manager):
    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle scouting related tasks.

        This manager should calculate where and when to scout.
        Assign units, and call related combat classes to execute
        the scouting logic.

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

        self.worker_scouts: BaseUnit = WorkerScouts(ai, config, mediator)
        self._assigned_worker_scout: bool = False
        self._scout_points_behind_natural: list[Point2] = []
        self._scv_points_to_check: dict[Race, list[Point2]] = {
            Race.Protoss: [],
            Race.Terran: [],
            Race.Zerg: [],
        }
        self._scv_scout_start_time: dict[Race, float] = {
            Race.Protoss: 44.0,
            Race.Terran: 44.0,
            Race.Zerg: 44.0,
        }

    async def initialise(self) -> None:
        """Precalculate spots to scout"""

        if self.ai.enemy_race == Race.Protoss:
            self._scv_points_to_check[self.ai.enemy_race].extend(
                self.behind_natural_positions
            )
            self._scv_points_to_check[self.ai.enemy_race].append(
                self.manager_mediator.get_own_nat.towards(
                    self.ai.game_info.map_center, 15.0
                )
            )
        elif self.ai.enemy_race == Race.Terran:
            for base_loc in self.manager_mediator.get_own_expansions[:4]:
                self._scv_points_to_check[self.ai.enemy_race].append(base_loc[0])

    @property
    def behind_natural_positions(self) -> list[Point2]:
        """
        Get positions behind our own natural to scout.
        This is useful for spotting cannon rushes.

        Returns
        -------
        The desired positions to check
        """
        own_nat: Point2 = self.manager_mediator.get_own_nat
        positions: list[Point2] = []
        # get position behind the minerals
        nat_minerals: Units = self.ai.mineral_field.closer_than(10, own_nat)
        behind_nat_mineral_line: Point2 = nat_minerals.center.towards(own_nat, -4)
        positions.append(behind_nat_mineral_line)
        # get position behind the gas buildings
        gas_buildings: Units = self.ai.vespene_geyser.closer_than(10, own_nat)
        positions.append(
            gas_buildings.furthest_to(
                self.ai.main_base_ramp.bottom_center
            ).position.towards(own_nat, -4)
        )
        return positions

    async def update(self, iteration: int) -> None:
        self._assign_worker_scout()
        self._unassign_worker_scout()
        if self._assigned_worker_scout:
            self._execute_worker_scout()

    def _assign_worker_scout(self) -> None:
        if self._assigned_worker_scout:
            return

        # Scout only assigned vs T/P
        if (
            self.ai.enemy_race != Race.Zerg
            and self.ai.time > self._scv_scout_start_time[self.ai.enemy_race]
        ):
            if worker := self.manager_mediator.select_worker(
                target_position=self.manager_mediator.get_own_nat
            ):
                self.manager_mediator.assign_role(
                    tag=worker.tag, role=UnitRole.SCOUTING
                )
                self._assigned_worker_scout = True

    def _execute_worker_scout(self):
        self.worker_scouts.execute(
            units=self.manager_mediator.get_units_from_role(
                role=UnitRole.SCOUTING, unit_type=UnitID.SCV
            ),
            points_to_check=self._scv_points_to_check[self.ai.enemy_race],
        )

    def _unassign_worker_scout(self) -> None:
        # provide a bit of time to issue scout commands
        # otherwise unassignment can hit prematurely
        if self.ai.time < self._scv_scout_start_time[self.ai.enemy_race] + 2.0:
            return

        scouting_scvs: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.SCOUTING, unit_type=UnitID.SCV
        )

        if not scouting_scvs:
            return

        ground_near_workers: dict[
            int, Units
        ] = self.manager_mediator.get_units_in_range(
            start_points=scouting_scvs,
            distances=15,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )

        for scv in scouting_scvs:
            if ground_near_workers[scv.tag](WORKER_TYPES):
                continue

            if (
                scv.health_percentage < 0.2
                or len(scv.orders) == 0
                or cy_distance_to(scv.position, self.manager_mediator.get_own_nat)
                > 90.0
            ):
                self.manager_mediator.assign_role(tag=scv.tag, role=UnitRole.GATHERING)
