from typing import TYPE_CHECKING

from sc2.unit import Unit
from sc2.units import Units

from ares import ManagerMediator
from ares.consts import UnitRole
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID


from bot.combat.base_unit import BaseUnit
from bot.combat.worker_defenders import WorkerDefenders

if TYPE_CHECKING:
    from ares import AresBot


class WorkerDefenceManager(Manager):
    MIN_HEALTH_PERC: float = 0.24

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

        self.worker_defenders_behavior: BaseUnit = WorkerDefenders(ai, config, mediator)

        self._enemy_to_workers_required: dict[UnitID, int] = {
            UnitID.DRONE: 1,
            UnitID.PROBE: 1,
            UnitID.SCV: 1,
            UnitID.ZEALOT: 4,
            UnitID.ZERGLING: 2,
        }

    @property
    def enabled(self) -> bool:
        """Here for later, if we have enough units we should stop assigning worker defence."""
        return True

    async def update(self, iteration: int) -> None:
        enemy_near_bases: dict[
            int, set[int]
        ] = self.manager_mediator.get_ground_enemy_near_bases
        defender_scvs: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.DEFENDING, unit_type=UnitID.SCV
        )
        if self.enabled:
            self._assign_worker_defenders(defender_scvs, enemy_near_bases)

        self._unassign_worker_defenders(defender_scvs, enemy_near_bases)
        self._execute_worker_defenders(defender_scvs)

    def _assign_worker_defenders(
        self, defender_scvs: Units, enemy_near_bases: dict[int, set[int]]
    ) -> None:
        if not enemy_near_bases:
            return

        scvs: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.GATHERING, unit_type=UnitID.SCV
        ).filter(lambda worker: worker.health_percentage > self.MIN_HEALTH_PERC)
        if not scvs:
            return

        num_scvs_required: int = 0
        num_enemy: int = 0
        for base_tag, enemy_tags in enemy_near_bases.items():
            # look for enemy units we are interested in
            enemy_interested_in: list[Unit] = [
                u
                for u in self.ai.enemy_units
                if u.tag in enemy_tags and u.type_id in self._enemy_to_workers_required
            ]
            num_enemy += len(enemy_interested_in)
            for enemy in enemy_interested_in:
                num_scvs_required += self._enemy_to_workers_required[enemy.type_id]

        num_scvs_required = min(num_scvs_required, 16)
        num_scvs_required -= len(defender_scvs)
        if num_scvs_required > 0 and num_enemy > 2:
            num_assigned: int = 0
            for scv in scvs:
                if num_assigned >= num_scvs_required:
                    break

                tag = scv.tag
                self.manager_mediator.remove_worker_from_mineral(worker_tag=tag)
                self.manager_mediator.assign_role(tag=tag, role=UnitRole.DEFENDING)
                num_assigned += 1

    def _unassign_worker_defenders(
        self, defender_scvs: Units, enemy_near_bases: dict[int, set[int]]
    ) -> None:
        for scv in defender_scvs:
            if not enemy_near_bases or scv.health_percentage <= self.MIN_HEALTH_PERC:
                self.manager_mediator.assign_role(tag=scv.tag, role=UnitRole.GATHERING)

    def _execute_worker_defenders(self, defender_scvs: Units) -> None:
        self.worker_defenders_behavior.execute(defender_scvs)
