#!/usr/bin/env bash
# Run all unit tests manually.
#
# Usage:
#   ./test.sh                      # run the whole test suite
#   ./test.sh tests/test_tasks_roles.py   # run specific test file(s)
#
# Environment:
#   PYTHON  Python interpreter to use (default: python3)
#   PYTEST_ADDOPTS_EXTRA  extra pytest options appended to the run
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

export ENVIRONMENT="${ENVIRONMENT:-development}"
export TELEMETRY_ENABLED="${TELEMETRY_ENABLED:-0}"
export SECRET="${SECRET:-testsecret}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-jLscvNBMBMrZWAMXpmRY1EVblCKUH7Kl-wIwiskLpT0=}"
export FIEF_CLIENT_ID="${FIEF_CLIENT_ID:-FiefClientID}"
export FIEF_CLIENT_SECRET="${FIEF_CLIENT_SECRET:-FiefClientSecret}"
export FIEF_MAIN_USER_EMAIL="${FIEF_MAIN_USER_EMAIL:-anne@bretagne.duchy}"
export FIEF_MAIN_USER_PASSWORD="${FIEF_MAIN_USER_PASSWORD:-herminetincture}"

if [ "$#" -gt 0 ]; then
    TEST_TARGETS=("$@")
else
    TEST_TARGETS=(
        tests/test_app.py
        tests/test_apps_api_clients.py
        tests/test_apps_api_email_templates.py
        tests/test_apps_api_oauth_providers.py
        tests/test_apps_api_permissions.py
        tests/test_apps_api_roles.py
        tests/test_apps_api_tenants.py
        tests/test_apps_api_user_fields.py
        tests/test_apps_api_users.py
        tests/test_apps_api_webhooks.py
        tests/test_apps_auth.py
        tests/test_apps_auth_auth.py
        tests/test_apps_auth_dashboard.py
        tests/test_apps_auth_forms_register.py
        tests/test_apps_auth_locale.py
        tests/test_apps_auth_oauth.py
        tests/test_apps_auth_register.py
        tests/test_apps_auth_reset.py
        tests/test_apps_auth_token.py
        tests/test_apps_auth_user.py
        tests/test_apps_auth_well_known.py
        tests/test_apps_dashboard_api_keys.py
        tests/test_apps_dashboard_auth.py
        tests/test_apps_dashboard_clients.py
        tests/test_apps_dashboard_email_templates.py
        tests/test_apps_dashboard_oauth_providers.py
        tests/test_apps_dashboard_permissions.py
        tests/test_apps_dashboard_roles.py
        tests/test_apps_dashboard_tenants.py
        tests/test_apps_dashboard_themes.py
        tests/test_apps_dashboard_user_fields.py
        tests/test_apps_dashboard_users.py
        tests/test_apps_dashboard_webhooks.py
        tests/test_apps_security_headers.py
        tests/test_db_types.py
        tests/test_dependencies_login_hint.py
        tests/test_dependencies_user_field.py
        tests/test_forms.py
        tests/test_models_tenant.py
        tests/test_models_user.py
        tests/test_models_user_field_value.py
        tests/test_repositories_user.py
        tests/test_schemas_generics.py
        tests/test_services_email_provider_base.py
        tests/test_services_email_provider_smtp.py
        tests/test_services_email_template.py
        tests/test_services_is_localhost.py
        tests/test_services_tenant_email_domain.py
        tests/test_services_user_roles.py
        tests/test_services_webhooks_delivery.py
        tests/test_services_webhooks_trigger.py
        tests/test_tasks_cleanup.py
        tests/test_tasks_email_verification.py
        tests/test_tasks_forgot_password.py
        tests/test_tasks_register.py
        tests/test_tasks_roles.py
        tests/test_tasks_user_roles.py
        tests/test_tasks_webhooks.py
    )
fi

exec "$PYTHON" -m pytest -o addopts="" ${PYTEST_ADDOPTS_EXTRA:-} "${TEST_TARGETS[@]}"
