import time
import random
from brownie import accounts
from enum import Enum
from rich.console import Console

from scripts.systems.badger_system import BadgerSystem
from helpers.sett.SnapshotManager import SnapshotManager
from .provisioners import (
    BaseProvisioner,
    DiggRewardsProvisioner,
    DiggLpMetaFarmProvisioner,
    SushiDiggWbtcLpOptimizerProvisioner,
)
from .actors import (
    UserActor,
    SettKeeperActor,
    StrategyKeeperActor,
    ChainActor,
    DiggActor,
)

console = Console()

# Provision num users for sim.
NUM_USERS = 10


class SimulationManagerState(Enum):
    IDLE = 0
    PROVISIONED = 1
    RANDOMIZED = 2
    RUNNING = 3


# SimulationManager is meant to be initialized per test and run once.
class SimulationManager:
    def __init__(
        self,
        badger: BadgerSystem,
        snap: SnapshotManager,
        settId: str,
        seed: int = 0,  # Default seed is 0 or unset, will generate.
    ):
        self.accounts = accounts[6:]  # Use the 7th account onwards.
        # User accounts (need to be provisioned before running sim).
        self.users = []

        self.badger = badger
        self.snap = snap
        self.sett = badger.getSett(settId)
        self.strategy = badger.getStrategy(settId)
        self.want = badger.getStrategyWant(settId)
        self.settKeeper = accounts.at(self.sett.keeper(), force=True)
        self.strategyKeeper = accounts.at(self.strategy.keeper(), force=True)

        # Actors generate valid actions based on the actor type. For example,
        # user actors need to have deposited first before they can withdraw
        # (withdraw before deposit is an invalid action).
        self.actors = [
            SettKeeperActor(self, self.settKeeper),
            StrategyKeeperActor(self, self.strategyKeeper),
            DiggActor(self, self.badger.deployer),
            ChainActor(),
        ]
        # Ordered valid actions generated by actors.
        self.actions = []

        self.state = SimulationManagerState.IDLE

        # Track seed so we can configure this value if we want to repro test failures.
        self.seed = seed
        if self.seed == 0:
            self.seed = int(time.time())
        console.print(f"initialized simulation manager with seed: {self.seed}")
        random.seed(self.seed)
        self.provisioner = self._initProvisioner(self.strategy.getName())

    def provision(self) -> None:
        if self.state != SimulationManagerState.IDLE:
            raise Exception(f"invalid state: {self.state}")

        accountsUsed = set([])
        while len(self.users) < NUM_USERS:
            idx = int(random.random()*len(self.accounts))
            if idx in accountsUsed:
                continue

            self.users.append(self.accounts[idx])
            accountsUsed.add(idx)

        self.provisioner._distributeTokens(self.users)
        self.provisioner._distributeWant(self.users)
        self._provisionUserActors()
        console.print(f"provisioned {len(self.users)} users {len(self.actors)} actors")

        self.state = SimulationManagerState.PROVISIONED

    def randomize(self, numActions: int) -> None:
        if self.state != SimulationManagerState.PROVISIONED:
            raise Exception(f"invalid state: {self.state}")

        for i in range(0, numActions):
            # Pick a random actor and generate an action.
            idx = int(random.random() * len(self.actors))
            self.actions.append(self.actors[idx].generateAction())

        console.print(f"randomized {numActions} actions")

        self.state = SimulationManagerState.RANDOMIZED

    def run(self) -> None:
        if self.state != SimulationManagerState.RANDOMIZED:
            raise Exception(f"invalid state: {self.state}")
        self.state = SimulationManagerState.RUNNING

        console.print(f"running {len(self.actions)} actions")

        for action in self.actions:
            action.run()

    def _initProvisioner(self, name) -> BaseProvisioner:
        if name == "StrategyDiggRewards":
            return DiggRewardsProvisioner(self)
        if name == "StrategyDiggLpMetaFarm":
            return DiggLpMetaFarmProvisioner(self)
        if name == "StrategySushiDiggWbtcLpOptimizer":
            return SushiDiggWbtcLpOptimizerProvisioner(self)
        raise Exception(f"invalid strategy name (no provisioner): {name}")

    def _provisionUserActors(self) -> None:
        # Add all users as actors the sim.
        for user in self.users:
            self.actors.append(UserActor(self, user))
