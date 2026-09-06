"""Stable dependency keys published by the protected framework SDK."""

from businessos.di import DependencyKey
from businessos.persistence import Database, UnitOfWorkFactory

DATABASE = DependencyKey[Database]("businessos.database")
UNIT_OF_WORK_FACTORY = DependencyKey[UnitOfWorkFactory]("businessos.unit_of_work_factory")
