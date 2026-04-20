from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from geoalchemy2 import Geography, Geometry, alembic_helpers
from sqlalchemy import engine_from_config, pool

import hideandseek_models  # noqa: F401 — registers all tables on Base.metadata
from hideandseek_models.base import Base
from hideandseek_models.geo_types import ShapelyGeography, ShapelyGeometry


def _render_item(obj_type, obj, autogen_context):
    # geoalchemy2's render_item uses obj.__class__.__name__ and assumes the
    # class is importable from `geoalchemy2`. Our custom ShapelyGeography /
    # ShapelyGeometry subclasses break that — intercept and emit imports
    # from hideandseek_models.geo_types. All other types fall through.
    if obj_type == 'type' and isinstance(obj, (ShapelyGeography, ShapelyGeometry)):
        autogen_context.imports.add(
            f'from hideandseek_models.geo_types import {obj.__class__.__name__}'
        )
        return repr(obj)
    if obj_type == 'type' and isinstance(obj, (Geometry, Geography)):
        return alembic_helpers.render_item(obj_type, obj, autogen_context)
    return False


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # Reflection returns a bare Geography/Geometry; the ORM declares the
    # Shapely-converting subclass. DDL is identical, so silence the false
    # "modify_type" diff whenever both sides are the same base spatial type.
    if isinstance(metadata_type, (ShapelyGeometry, Geometry)) and isinstance(
        inspected_type, Geometry
    ):
        return False
    if isinstance(metadata_type, (ShapelyGeography, Geography)) and isinstance(
        inspected_type, Geography
    ):
        return False
    return None


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get('DATABASE_URL')
if not database_url:
    msg = 'DATABASE_URL environment variable is required for alembic migrations'
    raise RuntimeError(msg)
config.set_main_option('sqlalchemy.url', database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        include_object=alembic_helpers.include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=_render_item,
        compare_type=_compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=alembic_helpers.include_object,
            process_revision_directives=alembic_helpers.writer,
            render_item=_render_item,
            compare_type=_compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
