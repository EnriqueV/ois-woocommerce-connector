<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('Expires: 0');

require_once __DIR__ . '/sync_lib.php';

function cron_send_json(int $status, array $payload): void {
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    cron_send_json(405, [
        'ok' => false,
        'error' => 'Método no permitido. Usa GET.',
    ]);
}

try {
    $cfg = load_config();
    $mode = (string) ($_GET['mode'] ?? ($cfg['sync']['mode'] ?? 'new'));
    $syncResult = run_sync($mode, false);

    cron_send_json(200, [
        'ok' => true,
        'trigger' => 'cron_get',
        'mode' => $mode,
        'message' => $syncResult['message'] ?? '',
        'summary' => $syncResult['summary'] ?? null,
        'result' => $syncResult['result'] ?? null,
        'executed_at' => date('c'),
    ]);
} catch (InvalidArgumentException $e) {
    write_app_log('error', 'Cron sync validation error.', ['error' => $e->getMessage()]);
    cron_send_json(400, ['ok' => false, 'error' => $e->getMessage()]);
} catch (Throwable $e) {
    write_app_log('error', 'Cron sync fatal error.', ['error' => $e->getMessage()]);
    cron_send_json(500, ['ok' => false, 'error' => $e->getMessage()]);
}
