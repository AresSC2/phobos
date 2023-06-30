from dataclasses import dataclass

from sc2.units import Units

from ares import ManagerMediator, UnitTreeQueryType, WORKER_TYPES
from ares.cython_extensions.units_utils import cy_closest_to
from bot.combat.base_unit import BaseUnit


@dataclass
class WorkerScouts(BaseUnit):
    """Execute behavior for mines and medivac in a mine drop.

    Called from `ScoutManager`

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator
        Used for getting information from managers in Ares.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator
    _queued_worker_scout_commands: bool = False

    def execute(self, units: Units, **kwargs) -> None:
        """Execute the mine drop.

        Parameters
        ----------
        units : list[Unit]
            The units we want MedivacMineDrop to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        medivac_tag_to_mine_tracker : dict[int, dict]
            Tracker detailing medivac tag to mine tags.
            And target for the mine drop.

        """
        assert (
            "points_to_check" in kwargs
        ), "No value for `points_to_check` was passed into kwargs."

        ground_near_workers: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )

        for unit in units:
            enemy_near_worker: Units = ground_near_workers[unit.tag]
            if enemy_workers := [
                u for u in enemy_near_worker if u.type_id in WORKER_TYPES
            ]:
                unit.attack(cy_closest_to(unit.position, enemy_workers))
            elif not self._queued_worker_scout_commands:
                unit.move(self.mediator.get_own_nat)
                for pos in kwargs["points_to_check"]:
                    unit.move(pos, queue=True)
                self._queued_worker_scout_commands = True
