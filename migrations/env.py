from alembic import context
from hub.config import Settings
from hub.db import Base
from hub.gmail_setup import GmailOAuthAttempt  # noqa: F401
from hub.memory_embeddings import MemoryEmbedding  # noqa: F401
from hub.memory_models import MemoryCandidate, MemoryLearningJob, MemorySettings  # noqa: F401
from hub.memory_summary import ConversationSummary  # noqa: F401
from sqlalchemy import create_engine

config = context.config
url = Settings.from_env().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
