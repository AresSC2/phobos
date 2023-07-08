from dataclasses import dataclass

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ares import ManagerMediator, UnitTreeQueryType
from ares.behaviors.combat.individual import WorkerKiteBack
from ares.cython_extensions.units_utils import cy_closest_to, cy_center
from bot.combat.base_unit import BaseUnit


@dataclass
class WorkerDefenders(BaseUnit):
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

        ground_near_workers: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )

        for worker in units:
            near_ground: Units = ground_near_workers[worker.tag]
            if near_ground:
                self.ai.register_behavior(
                    WorkerKiteBack(
                        unit=worker, target=cy_closest_to(worker.position, near_ground)
                    )
                )
            elif enemy_near_base := self.mediator.get_main_ground_threats_near_townhall:
                worker.attack(Point2(cy_center(enemy_near_base)))

            elif mfs := self.ai.mineral_field:
                worker.gather(cy_closest_to(worker.position, mfs))
