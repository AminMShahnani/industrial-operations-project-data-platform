from alembic import context
from operations.platform.config import Settings
from operations.platform.database import Base
from sqlalchemy import create_engine, pool

target_metadata = Base.metadata
settings = Settings()  # type: ignore[call-arg]
url = settings.database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
