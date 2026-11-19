<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
header('Expires: 0');

require_once __DIR__ . '/sync_lib.php';

function send_json(int $status, array $payload): void {
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function read_body_json(): array {
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') {
        return [];
    }

    $data = json_decode($raw, true);
    if (!is_array($data)) {
        send_json(400, ['ok' => false, 'error' => 'JSON inválido en el body.']);
    }

    return $data;
}

$action = $_GET['action'] ?? '';

try {
    if ($action === 'get_state') {
        send_json(200, ['ok' => true, 'data' => load_config()]);
    }

    if ($action === 'save_settings') {
        $body = read_body_json();
        $settings = $body['settings'] ?? null;
        if (!is_array($settings)) {
            send_json(400, ['ok' => false, 'error' => "Body esperado: { settings: {...} }"]);
        }

        $cfg = load_config();
        $cfg['settings'] = array_replace($cfg['settings'], $settings);
        save_config($cfg);
        send_json(200, ['ok' => true]);
    }

    if ($action === 'save_programming') {
        $body = read_body_json();
        $programming = $body['programming'] ?? null;
        if (!is_array($programming)) {
            send_json(400, ['ok' => false, 'error' => "Body esperado: { programming: {...} }"]);
        }

        $cfg = load_config();
        $cfg['programming'] = array_replace_recursive($cfg['programming'], $programming);
        save_config($cfg);
        send_json(200, ['ok' => true]);
    }

    if ($action === 'save_sync_mode') {
        $body = read_body_json();
        $mode = (string) ($body['mode'] ?? '');
        if ($mode !== 'new' && $mode !== 'all') {
            send_json(400, ['ok' => false, 'error' => "Mode inválido. Usa 'new' o 'all'."]);
        }

        $cfg = load_config();
        $cfg['sync']['mode'] = $mode;
        save_config($cfg);
        send_json(200, ['ok' => true]);
    }

    if ($action === 'test_connection') {
        $result = test_ois_connection();

        send_json(200, [
            'ok' => true,
            'message' => $result['message'] ?? '',
            'summary' => $result['summary'] ?? null,
            'sample_products' => $result['sample_products'] ?? [],
        ]);
    }

    if ($action === 'sync') {
        $body = read_body_json();
        $mode = (string) ($body['mode'] ?? 'new');
        $syncResult = run_sync($mode, true);

        send_json(200, [
            'ok' => true,
            'message' => $syncResult['message'] ?? '',
            'summary' => $syncResult['summary'] ?? null,
            'created_products' => $syncResult['created_products'] ?? [],
            'updated_products' => $syncResult['updated_products'] ?? [],
            'skipped_products' => $syncResult['skipped_products'] ?? [],
            'error_details' => $syncResult['error_details'] ?? [],
            'retried_without_images' => $syncResult['retried_without_images'] ?? [],
            'result' => $syncResult['result'] ?? null,
        ]);
    }

    if ($action === 'create_categories') {
        $result = run_category_sync();

        send_json(200, [
            'ok' => true,
            'message' => $result['message'] ?? '',
            'summary' => $result['summary'] ?? null,
            'created_categories' => $result['created_categories'] ?? [],
            'delete_errors' => $result['delete_errors'] ?? [],
            'create_errors' => $result['create_errors'] ?? [],
        ]);
    }

    send_json(404, ['ok' => false, 'error' => 'Acción no encontrada.']);
} catch (InvalidArgumentException $e) {
    write_app_log('error', 'Sync/API validation error.', ['error' => $e->getMessage(), 'action' => $action]);
    send_json(400, ['ok' => false, 'error' => $e->getMessage()]);
} catch (Throwable $e) {
    write_app_log('error', 'Sync/API fatal error.', ['error' => $e->getMessage(), 'action' => $action]);
    send_json(500, ['ok' => false, 'error' => $e->getMessage()]);
}
