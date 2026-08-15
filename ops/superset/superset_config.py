import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://superset:{os.environ['SUPERSET_DB_PASSWORD']}"
    "@superset-db:5432/superset"
)

# No Redis/Celery in this local-dev setup (deliberate simplification -- low query volume,
# small pilot audience). Async chart loading / scheduled reports aren't available as a result.
#
# ENABLE_TEMPLATE_PROCESSING is required for Row Level Security's Jinja templates
# ({{ current_username() }}) to actually render -- defaults to False. Without it, RLS clauses
# are sent to the database as literal, un-rendered Jinja syntax, which matches nothing and fails
# closed (blocks all rows) rather than filtering correctly -- confirmed by testing. It must live
# *inside* FEATURE_FLAGS: Superset reads it via the feature flag manager
# (`is_feature_enabled("ENABLE_TEMPLATE_PROCESSING")` in jinja_context.py), not as a bare
# top-level config variable -- a bare `ENABLE_TEMPLATE_PROCESSING = True` shows up in
# `app.config` but is silently ignored by that check (also confirmed by testing).
FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": True}
