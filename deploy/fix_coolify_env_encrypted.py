#!/usr/bin/env python3
"""Generate and run a Coolify PHP script that inserts encrypted env vars."""
from __future__ import annotations

import subprocess
from pathlib import Path

ENV_PATH = Path("/etc/reciapp/recipe-backend.env")
SECRET_KEYS = {
    "DATABASE_URL",
    "AUTH_JWT_SECRET",
    "API_KEY",
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "OPENAI_API_KEY",
}


def php_single_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def main() -> None:
    pairs: list[tuple[str, str]] = []
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs.append((key.strip(), value))
    if not any(key == "PORT" for key, _ in pairs):
        pairs.append(("PORT", "8000"))

    items_php: list[str] = []
    for key, value in pairs:
        build = "false" if key in SECRET_KEYS else "true"
        items_php.append(
            "    ["
            f"'key' => '{php_single_quote(key)}', "
            f"'value' => '{php_single_quote(value)}', "
            f"'is_buildtime' => {build}"
            "]"
        )

    php = f"""<?php
require __DIR__ . '/vendor/autoload.php';
$app = require_once __DIR__ . '/bootstrap/app.php';
$kernel = $app->make(Illuminate\\Contracts\\Console\\Kernel::class);
$kernel->bootstrap();

use App\\Models\\EnvironmentVariable;
use App\\Models\\Application;

$appId = 1;
EnvironmentVariable::where('resourceable_type', Application::class)
    ->where('resourceable_id', $appId)
    ->delete();

$items = [
{',\n'.join(items_php)}
];

$order = 0;
foreach ($items as $item) {{
    $order++;
    EnvironmentVariable::create([
        'key' => $item['key'],
        'value' => $item['value'],
        'is_preview' => false,
        'is_multiline' => false,
        'is_literal' => true,
        'is_runtime' => true,
        'is_buildtime' => $item['is_buildtime'],
        'is_shown_once' => false,
        'resourceable_type' => Application::class,
        'resourceable_id' => $appId,
        'order' => $order,
        'version' => '4.0.0-beta.239',
    ]);
}}

$count = EnvironmentVariable::where('resourceable_type', Application::class)
    ->where('resourceable_id', $appId)
    ->where('is_preview', false)
    ->count();
$port = EnvironmentVariable::where('key', 'PORT')->where('is_preview', false)->first();
echo 'ok count=' . $count . ' PORT=' . ($port?->value ?? 'missing') . PHP_EOL;
"""

    local = Path("/tmp/coolify_fix_env.php")
    local.write_text(php)
    subprocess.run(["docker", "cp", str(local), "coolify:/var/www/html/coolify_fix_env.php"], check=True)
    subprocess.run(
        ["docker", "exec", "-u", "www-data", "coolify", "php", "/var/www/html/coolify_fix_env.php"],
        check=True,
    )
    subprocess.run(["docker", "exec", "coolify", "rm", "-f", "/var/www/html/coolify_fix_env.php"], check=True)


if __name__ == "__main__":
    main()
