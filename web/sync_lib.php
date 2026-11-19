<?php
declare(strict_types=1);

const CONFIG_FILE = __DIR__ . '/config.json';
const LOG_DIR = __DIR__ . '/logs';
const IMAGES_DIR = __DIR__ . '/images';
const SYNC_LIMIT = 5;
const OIS_SYNC_TAG_NAME = 'sincronizado by ois connector';
const OIS_SYNC_HASH_META_KEY = '_ois_connector_hash';

function default_config(): array {
    return [
        'settings' => [
            'OIS Products URL' => '',
            'Image URL' => '',
            'Local Images Directory' => '',
            'Public Images Base URL' => '',
            'DigitalOcean Spaces Endpoint' => '',
            'DigitalOcean Spaces Access Key' => '',
            'DigitalOcean Spaces Secret Key' => '',
            'DigitalOcean Spaces Directory' => 'file_img',
            'Token / API Key' => '',
            'WordPress URL' => '',
            'WordPress Username' => '',
            'WordPress Application Password' => '',
            'WordPress Client Key' => '',
            'WordPress Client Secret' => '',
        ],
        'programming' => [
            'days' => [
                'Lunes' => false,
                'Martes' => false,
                'Miércoles' => false,
                'Jueves' => false,
                'Viernes' => false,
                'Sábado' => false,
                'Domingo' => false,
            ],
            'time' => '',
        ],
        'sync' => [
            'mode' => 'new',
        ],
    ];
}

function load_config(): array {
    if (!file_exists(CONFIG_FILE)) {
        $cfg = default_config();
        save_config($cfg);
        return $cfg;
    }

    $raw = file_get_contents(CONFIG_FILE);
    if ($raw === false) {
        throw new RuntimeException('No se pudo leer config.json');
    }

    $data = json_decode($raw, true);
    if (!is_array($data)) {
        $cfg = default_config();
        save_config($cfg);
        return $cfg;
    }

    return array_replace_recursive(default_config(), $data);
}

function save_config(array $cfg): void {
    $json = json_encode($cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        throw new RuntimeException('No se pudo serializar la configuración.');
    }
    if (file_put_contents(CONFIG_FILE, $json . PHP_EOL, LOCK_EX) === false) {
        throw new RuntimeException('No se pudo guardar config.json');
    }
}

function write_app_log(string $level, string $message, array $context = []): void {
    if (!is_dir(LOG_DIR)) {
        @mkdir(LOG_DIR, 0775, true);
    }

    $logFile = LOG_DIR . '/sync-' . date('Y-m-d') . '.log';
    $line = '[' . date('c') . '] [' . strtoupper($level) . '] ' . $message;
    if ($context !== []) {
        $json = json_encode($context, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($json !== false) {
            $line .= ' ' . $json;
        }
    }
    $line .= PHP_EOL;

    @file_put_contents($logFile, $line, FILE_APPEND | LOCK_EX);
}

function normalize_wp_url(string $url): string {
    $normalized = rtrim(trim($url), '/');
    $normalized = preg_replace('#://www\.#', '://', $normalized, 1) ?? $normalized;
    $normalized = preg_replace('#/wp-json$#', '', $normalized) ?? $normalized;
    return $normalized;
}

function normalize_public_images_base_url(string $url): string {
    $normalized = rtrim(trim($url), '/');
    return $normalized;
}

function default_public_images_base_url(array $settings): string {
    $configured = trim((string) ($settings['Public Images Base URL'] ?? ''));
    if ($configured !== '') {
        return normalize_public_images_base_url($configured);
    }

    $wp = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    if ($wp === '') {
        return '';
    }

    return $wp . '/ois/images';
}

function default_local_images_directory(array $settings): string {
    $configured = trim((string) ($settings['Local Images Directory'] ?? ''));
    if ($configured !== '') {
        return rtrim($configured, '/');
    }

    return IMAGES_DIR;
}

function normalize_spaces_endpoint(string $endpoint): string {
    return rtrim(trim($endpoint), '/');
}

function spaces_public_base_url(array $settings): string {
    $endpoint = normalize_spaces_endpoint((string) ($settings['DigitalOcean Spaces Endpoint'] ?? ''));
    if ($endpoint === '') {
        return '';
    }

    $directory = trim((string) ($settings['DigitalOcean Spaces Directory'] ?? 'file_img'), " \t\n\r\0\x0B/");
    return $directory !== '' ? $endpoint . '/' . $directory : $endpoint;
}

function spaces_is_configured(array $settings): bool {
    return normalize_spaces_endpoint((string) ($settings['DigitalOcean Spaces Endpoint'] ?? '')) !== ''
        && trim((string) ($settings['DigitalOcean Spaces Access Key'] ?? '')) !== ''
        && trim((string) ($settings['DigitalOcean Spaces Secret Key'] ?? '')) !== '';
}

function spaces_region_from_endpoint(string $endpoint): string {
    $host = parse_url($endpoint, PHP_URL_HOST);
    if (!is_string($host) || $host === '') {
        $host = preg_replace('#^https?://#', '', $endpoint) ?? $endpoint;
        $host = explode('/', $host)[0] ?? $host;
    }

    $parts = explode('.', $host);
    if (count($parts) >= 3 && $parts[1] !== '') {
        return $parts[1];
    }

    return 'nyc3';
}

function encode_s3_path(string $path): string {
    $segments = array_map('rawurlencode', explode('/', ltrim($path, '/')));
    return '/' . implode('/', $segments);
}

function hmac_sha256(string $key, string $data, bool $raw = true): string {
    return hash_hmac('sha256', $data, $key, $raw);
}

function build_ois_url(string $oisUrl, string $token): string {
    $sep = (strpos($oisUrl, '?') !== false) ? '&' : '?';
    return rtrim($oisUrl, '/') . $sep . 'key=' . $token;
}

function slugify_filename(string $value): string {
    $value = trim($value);
    if ($value === '') {
        return 'producto';
    }

    if (function_exists('iconv')) {
        $converted = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $value);
        if ($converted !== false) {
            $value = $converted;
        }
    }

    $value = strtolower($value);
    $value = preg_replace('/[^a-z0-9]+/', '-', $value) ?? $value;
    $value = trim($value, '-');
    return $value !== '' ? $value : 'producto';
}

function detect_image_extension(string $fileUrl, string $nameFile = ''): string {
    $path = parse_url($fileUrl, PHP_URL_PATH);
    $candidate = $nameFile !== '' ? $nameFile : (is_string($path) ? basename($path) : '');
    $ext = strtolower(pathinfo($candidate, PATHINFO_EXTENSION));
    if ($ext === '') {
        return 'jpg';
    }

    $allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp'];
    return in_array($ext, $allowed, true) ? $ext : 'jpg';
}

function ensure_images_dir(string $directory): void {
    if (!is_dir($directory)) {
        $created = @mkdir($directory, 0775, true);
        if (!$created && !is_dir($directory)) {
            $lastError = error_get_last();
            $message = $lastError['message'] ?? 'No se pudo crear el directorio.';
            throw new RuntimeException("No se pudo crear el directorio de imágenes '{$directory}': {$message}");
        }
    }

    if (!is_writable($directory)) {
        throw new RuntimeException("El directorio de imágenes no tiene permisos de escritura: {$directory}");
    }
}

function download_binary_file(string $url): string {
    $ch = curl_init($url);
    if ($ch === false) {
        throw new RuntimeException('No se pudo inicializar cURL para imagen.');
    }

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 45,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_HTTPHEADER => [
            'User-Agent: WooConnectorPHP/1.0',
        ],
    ]);

    $body = curl_exec($ch);
    if ($body === false) {
        $error = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException("Error descargando imagen: {$error}");
    }

    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($status !== 200) {
        throw new RuntimeException("Descarga de imagen falló con HTTP {$status}");
    }

    return $body;
}

function store_local_image(array $settings, array $image, string $productName, int $itemId, int $position): ?array {
    $fileUrl = trim((string) ($image['fileurl'] ?? ''));
    if ($fileUrl === '') {
        return null;
    }

    $publicBaseUrl = default_public_images_base_url($settings);
    if ($publicBaseUrl === '') {
        return null;
    }

    $localImagesDirectory = default_local_images_directory($settings);
    ensure_images_dir($localImagesDirectory);

    $extension = detect_image_extension($fileUrl, (string) ($image['nameFile'] ?? ''));
    $filename = slugify_filename($productName) . '-' . $itemId . '-' . $position . '.' . $extension;
    $localPath = $localImagesDirectory . '/' . $filename;

    if (!file_exists($localPath) || filesize($localPath) === 0) {
        $binary = download_binary_file($fileUrl);
        $written = @file_put_contents($localPath, $binary, LOCK_EX);
        if ($written === false) {
            $lastError = error_get_last();
            $message = $lastError['message'] ?? 'Error desconocido al escribir archivo.';
            throw new RuntimeException("No se pudo guardar la imagen local {$filename} en {$localPath}: {$message}");
        }
        write_app_log('info', 'Imagen descargada localmente.', [
            'product' => $productName,
            'item_id' => $itemId,
            'file' => $filename,
            'directory' => $localImagesDirectory,
        ]);
    }

    return [
        'src' => $publicBaseUrl . '/' . rawurlencode($filename),
        'local_file' => $filename,
        'local_path' => $localPath,
        ];
}

function mime_type_from_extension(string $path): string {
    $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
    return match ($ext) {
        'jpg', 'jpeg' => 'image/jpeg',
        'png' => 'image/png',
        'gif' => 'image/gif',
        'webp' => 'image/webp',
        default => 'application/octet-stream',
    };
}

function resolve_wp_media_auth(array $settings): ?string {
    $wpUser = trim((string) ($settings['WordPress Username'] ?? ''));
    $wpAppPassword = trim((string) ($settings['WordPress Application Password'] ?? ''));
    if ($wpUser !== '' && $wpAppPassword !== '') {
        return base64_encode($wpUser . ':' . $wpAppPassword);
    }

    $ck = trim((string) ($settings['WordPress Client Key'] ?? ''));
    $cs = trim((string) ($settings['WordPress Client Secret'] ?? ''));
    if ($ck !== '' && $cs !== '') {
        return base64_encode($ck . ':' . $cs);
    }

    return null;
}

function upload_binary_to_wp_media(array $settings, string $binary, string $filename): ?array {
    if ($binary === '') {
        return null;
    }

    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $auth = resolve_wp_media_auth($settings);
    if ($baseUrl === '' || $auth === null) {
        write_app_log('warning', 'No se pudo autenticar upload al media library.', [
            'file' => $filename,
            'reason' => 'Faltan credenciales de WordPress Username/Application Password o Woo credentials.',
        ]);
        return null;
    }

    $endpoint = $baseUrl . '/wp-json/wp/v2/media';
    $headers = [
        'Content-Type: ' . mime_type_from_extension($filename),
        'Content-Disposition: attachment; filename="' . addslashes($filename) . '"',
        'Authorization: Basic ' . $auth,
        'Accept: application/json',
        'User-Agent: WooConnectorPHP/1.0',
    ];

    $ch = curl_init($endpoint);
    if ($ch === false) {
        return null;
    }

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $binary,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => 45,
        CURLOPT_CONNECTTIMEOUT => 10,
    ]);

    $responseBody = curl_exec($ch);
    if ($responseBody === false) {
        $error = curl_error($ch);
        curl_close($ch);
        write_app_log('warning', 'No se pudo subir imagen al media library.', [
            'file' => $filename,
            'error' => $error,
        ]);
        return null;
    }

    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $data = json_decode($responseBody, true);
    if (!is_array($data) || ($status !== 200 && $status !== 201) || !isset($data['id'])) {
        write_app_log('warning', 'WordPress media upload rechazado.', [
            'file' => $filename,
            'status' => $status,
            'response' => is_array($data) ? $data : $responseBody,
        ]);
        return null;
    }

    write_app_log('info', 'Imagen subida al media library.', [
        'file' => $filename,
        'media_id' => $data['id'],
        'source_url' => $data['source_url'] ?? '',
    ]);

    return [
        'id' => $data['id'],
        'source_url' => $data['source_url'] ?? '',
    ];
}

function upload_binary_to_digitalocean_spaces(array $settings, string $binary, string $filename): ?array {
    if ($binary === '' || !spaces_is_configured($settings)) {
        return null;
    }

    $endpoint = normalize_spaces_endpoint((string) ($settings['DigitalOcean Spaces Endpoint'] ?? ''));
    $accessKey = trim((string) ($settings['DigitalOcean Spaces Access Key'] ?? ''));
    $secretKey = trim((string) ($settings['DigitalOcean Spaces Secret Key'] ?? ''));
    $directory = trim((string) ($settings['DigitalOcean Spaces Directory'] ?? 'file_img'), " \t\n\r\0\x0B/");
    $objectKey = $directory !== '' ? $directory . '/' . $filename : $filename;
    $canonicalUri = encode_s3_path($objectKey);
    $publicUrl = $endpoint . $canonicalUri;

    $host = parse_url($endpoint, PHP_URL_HOST);
    if (!is_string($host) || $host === '') {
        throw new RuntimeException('DigitalOcean Spaces Endpoint inválido.');
    }

    $region = spaces_region_from_endpoint($endpoint);
    $amzDate = gmdate('Ymd\THis\Z');
    $dateStamp = gmdate('Ymd');
    $payloadHash = hash('sha256', $binary);
    $contentType = mime_type_from_extension($filename);
    $signedHeaders = 'content-type;host;x-amz-acl;x-amz-content-sha256;x-amz-date';

    $canonicalHeaders = implode("\n", [
        'content-type:' . $contentType,
        'host:' . $host,
        'x-amz-acl:public-read',
        'x-amz-content-sha256:' . $payloadHash,
        'x-amz-date:' . $amzDate,
        '',
    ]);

    $canonicalRequest = implode("\n", [
        'PUT',
        $canonicalUri,
        '',
        $canonicalHeaders,
        $signedHeaders,
        $payloadHash,
    ]);

    $credentialScope = "{$dateStamp}/{$region}/s3/aws4_request";
    $stringToSign = implode("\n", [
        'AWS4-HMAC-SHA256',
        $amzDate,
        $credentialScope,
        hash('sha256', $canonicalRequest),
    ]);

    $dateKey = hmac_sha256('AWS4' . $secretKey, $dateStamp);
    $dateRegionKey = hmac_sha256($dateKey, $region);
    $dateRegionServiceKey = hmac_sha256($dateRegionKey, 's3');
    $signingKey = hmac_sha256($dateRegionServiceKey, 'aws4_request');
    $signature = hash_hmac('sha256', $stringToSign, $signingKey);

    $headers = [
        'Authorization: AWS4-HMAC-SHA256 Credential=' . $accessKey . '/' . $credentialScope . ', SignedHeaders=' . $signedHeaders . ', Signature=' . $signature,
        'Content-Type: ' . $contentType,
        'Host: ' . $host,
        'x-amz-acl: public-read',
        'x-amz-content-sha256: ' . $payloadHash,
        'x-amz-date: ' . $amzDate,
        'User-Agent: WooConnectorPHP/1.0',
    ];

    $ch = curl_init($publicUrl);
    if ($ch === false) {
        return null;
    }

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST => 'PUT',
        CURLOPT_POSTFIELDS => $binary,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => 60,
        CURLOPT_CONNECTTIMEOUT => 10,
    ]);

    $responseBody = curl_exec($ch);
    if ($responseBody === false) {
        $error = curl_error($ch);
        curl_close($ch);
        write_app_log('warning', 'No se pudo subir imagen a DigitalOcean Spaces.', [
            'file' => $filename,
            'error' => $error,
        ]);
        return null;
    }

    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($status < 200 || $status >= 300) {
        write_app_log('warning', 'DigitalOcean Spaces rechazó la imagen.', [
            'file' => $filename,
            'status' => $status,
            'response' => $responseBody,
        ]);
        return null;
    }

    write_app_log('info', 'Imagen subida a DigitalOcean Spaces.', [
        'file' => $filename,
        'url' => $publicUrl,
    ]);

    return [
        'src' => $publicUrl,
        'object_key' => $objectKey,
    ];
}

function upload_remote_image_to_wp_media(array $settings, array $image, string $productName, int $itemId, int $position): ?array {
    $fileUrl = trim((string) ($image['fileurl'] ?? ''));
    if ($fileUrl === '') {
        return null;
    }

    $extension = detect_image_extension($fileUrl, (string) ($image['nameFile'] ?? ''));
    $filename = slugify_filename($productName) . '-' . $itemId . '-' . $position . '.' . $extension;
    $binary = download_binary_file($fileUrl);

    write_app_log('info', 'Imagen descargada desde OIS para media upload.', [
        'product' => $productName,
        'item_id' => $itemId,
        'file' => $filename,
    ]);

    $uploaded = upload_binary_to_wp_media($settings, $binary, $filename);
    if ($uploaded === null) {
        throw new RuntimeException("No se pudo subir la imagen {$filename} al Media Library de WordPress.");
    }

    return $uploaded;
}

function upload_remote_image_for_product(array $settings, array $image, string $productName, int $itemId, int $position): ?array {
    $fileUrl = trim((string) ($image['fileurl'] ?? ''));
    if ($fileUrl === '') {
        return null;
    }

    $extension = detect_image_extension($fileUrl, (string) ($image['nameFile'] ?? ''));
    $filename = slugify_filename($productName) . '-' . $itemId . '-' . $position . '.' . $extension;
    $binary = download_binary_file($fileUrl);

    if (spaces_is_configured($settings)) {
        $uploadedToSpaces = upload_binary_to_digitalocean_spaces($settings, $binary, $filename);
        if ($uploadedToSpaces === null) {
            throw new RuntimeException("No se pudo subir la imagen {$filename} a DigitalOcean Spaces.");
        }

        return $uploadedToSpaces;
    }

    write_app_log('info', 'Imagen descargada desde OIS para media upload.', [
        'product' => $productName,
        'item_id' => $itemId,
        'file' => $filename,
    ]);

    $uploaded = upload_binary_to_wp_media($settings, $binary, $filename);
    if ($uploaded === null) {
        throw new RuntimeException("No se pudo subir la imagen {$filename} al Media Library de WordPress.");
    }

    return $uploaded;
}

function curl_json_request(string $method, string $url, array $headers = [], ?array $body = null, int $timeout = 30): array {
    $ch = curl_init($url);
    if ($ch === false) {
        throw new RuntimeException('No se pudo inicializar cURL.');
    }

    $finalHeaders = array_merge(
        [
            'Accept: application/json',
            'User-Agent: WooConnectorPHP/1.0',
        ],
        $headers
    );

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => $finalHeaders,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_CONNECTTIMEOUT => 10,
    ]);

    if ($body !== null) {
        $jsonBody = json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($jsonBody === false) {
            throw new RuntimeException('No se pudo serializar el body JSON.');
        }
        curl_setopt($ch, CURLOPT_POSTFIELDS, $jsonBody);
    }

    $responseBody = curl_exec($ch);
    if ($responseBody === false) {
        $error = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException("Error de red: {$error}");
    }

    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    $data = json_decode($responseBody, true);
    if (!is_array($data)) {
        $data = ['raw' => $responseBody];
    }

    return [
        'status' => $status,
        'data' => $data,
        'raw' => $responseBody,
    ];
}

function validate_settings_required(array $settings): void {
    $required = [
        'OIS Products URL',
        'Token / API Key',
        'WordPress URL',
        'WordPress Client Key',
        'WordPress Client Secret',
    ];
    $missing = [];
    foreach ($required as $field) {
        if (trim((string) ($settings[$field] ?? '')) === '') {
            $missing[] = $field;
        }
    }
    if (count($missing) > 0) {
        throw new InvalidArgumentException('Faltan campos: ' . implode(', ', $missing));
    }
}

function fetch_ois_items(array $settings): array {
    $oisUrl = trim((string) ($settings['OIS Products URL'] ?? ''));
    $token = trim((string) ($settings['Token / API Key'] ?? ''));
    $url = build_ois_url($oisUrl, $token);

    $resp = curl_json_request('GET', $url);
    if ($resp['status'] !== 200) {
        throw new RuntimeException("OIS API error {$resp['status']}");
    }

    $loginStatus = $resp['data']['Login']['status'] ?? 'unknown';
    if ($loginStatus !== 'Logged In') {
        throw new RuntimeException("OIS autenticación fallida (status='{$loginStatus}').");
    }

    $items = $resp['data']['ResultItems'] ?? null;
    if (!is_array($items)) {
        throw new RuntimeException("Respuesta OIS inesperada: 'ResultItems' no es una lista.");
    }

    return $items;
}

function fetch_ois_item_groups(array $settings): array {
    $oisUrl = trim((string) ($settings['OIS Products URL'] ?? ''));
    $token = trim((string) ($settings['Token / API Key'] ?? ''));
    $url = build_ois_url($oisUrl, $token);

    $resp = curl_json_request('GET', $url);
    if ($resp['status'] !== 200) {
        throw new RuntimeException("OIS API error {$resp['status']}");
    }

    $loginStatus = $resp['data']['Login']['status'] ?? 'unknown';
    if ($loginStatus !== 'Logged In') {
        throw new RuntimeException("OIS autenticación fallida (status='{$loginStatus}').");
    }

    $groups = $resp['data']['ResultItemGroups'] ?? null;
    if (!is_array($groups)) {
        throw new RuntimeException("Respuesta OIS inesperada: 'ResultItemGroups' no es una lista.");
    }

    return $groups;
}

function category_name_key(string $name): string {
    return function_exists('mb_strtolower') ? mb_strtolower($name, 'UTF-8') : strtolower($name);
}

function extract_category_names_from_groups(array $groups): array {
    $names = [];
    $seen = [];

    foreach ($groups as $group) {
        if (!is_array($group)) {
            continue;
        }

        if ((int) ($group['active'] ?? 1) !== 1) {
            continue;
        }

        $name = trim((string) ($group['name'] ?? ''));
        $key = category_name_key($name);
        if ($name === '' || isset($seen[$key])) {
            continue;
        }

        $seen[$key] = true;
        $names[] = $name;
    }

    return $names;
}

function build_category_ids_by_group_id(array $groups, array $wooCategories): array {
    $wooIdsByName = [];
    foreach ($wooCategories as $category) {
        if (!is_array($category)) {
            continue;
        }

        $name = trim((string) ($category['name'] ?? ''));
        $id = (int) ($category['id'] ?? 0);
        if ($name === '' || $id <= 0) {
            continue;
        }

        $wooIdsByName[category_name_key($name)] = $id;
    }

    $categoryIdsByGroupId = [];
    foreach ($groups as $group) {
        if (!is_array($group)) {
            continue;
        }

        if ((int) ($group['active'] ?? 1) !== 1) {
            continue;
        }

        $groupId = (int) ($group['cItemGroupId'] ?? 0);
        $name = trim((string) ($group['name'] ?? ''));
        if ($groupId <= 0 || $name === '') {
            continue;
        }

        $wooCategoryId = $wooIdsByName[category_name_key($name)] ?? 0;
        if ($wooCategoryId > 0) {
            $categoryIdsByGroupId[$groupId] = $wooCategoryId;
        }
    }

    return $categoryIdsByGroupId;
}

function fetch_ois_images(array $settings): array {
    $imagesUrl = trim((string) ($settings['Image URL'] ?? ''));
    $token = trim((string) ($settings['Token / API Key'] ?? ''));
    if ($imagesUrl === '') {
        return [];
    }

    $url = build_ois_url($imagesUrl, $token);
    $resp = curl_json_request('GET', $url);
    if ($resp['status'] !== 200) {
        throw new RuntimeException("OIS Images API error {$resp['status']}");
    }

    $loginStatus = $resp['data']['Login']['status'] ?? 'unknown';
    if ($loginStatus !== 'Logged In') {
        throw new RuntimeException("OIS imágenes autenticación fallida (status='{$loginStatus}').");
    }

    $images = $resp['data']['ResultImages'] ?? null;
    if (!is_array($images)) {
        throw new RuntimeException("Respuesta OIS inesperada: 'ResultImages' no es una lista.");
    }

    $grouped = [];
    foreach ($images as $image) {
        if (!is_array($image)) {
            continue;
        }

        $itemId = (int) ($image['cItemId'] ?? 0);
        $fileUrl = trim((string) ($image['fileurl'] ?? ''));
        if ($itemId <= 0 || $fileUrl === '') {
            continue;
        }

        $grouped[$itemId][] = $image;
    }

    foreach ($grouped as $itemId => $itemImages) {
        usort($itemImages, static function (array $left, array $right): int {
            $leftPrimary = (int) ($left['primary'] ?? 0);
            $rightPrimary = (int) ($right['primary'] ?? 0);
            if ($leftPrimary !== $rightPrimary) {
                return $rightPrimary <=> $leftPrimary;
            }

            $leftActive = (int) ($left['active'] ?? 0);
            $rightActive = (int) ($right['active'] ?? 0);
            if ($leftActive !== $rightActive) {
                return $rightActive <=> $leftActive;
            }

            return ((int) ($left['cItemFileXrefId'] ?? 0)) <=> ((int) ($right['cItemFileXrefId'] ?? 0));
        });

        $seen = [];
        $normalized = [];
        foreach ($itemImages as $image) {
            $fileUrl = trim((string) ($image['fileurl'] ?? ''));
            if ($fileUrl === '' || isset($seen[$fileUrl])) {
                continue;
            }
            $seen[$fileUrl] = true;
            $normalized[] = [
                'fileurl' => $fileUrl,
                'nameFile' => $image['nameFile'] ?? '',
            ];
        }

        $grouped[$itemId] = $normalized;
    }

    return $grouped;
}

function map_to_woo_products(array $items, array $imagesByItemId, array $categoryIdsByGroupId = [], int $syncTagId = 0): array {
    $cfg = load_config();
    $products = [];
    $slice = array_slice($items, 0, SYNC_LIMIT);

    foreach ($slice as $item) {
        if (!is_array($item)) {
            continue;
        }

        $name = trim((string) ($item['name'] ?? ''));
        if ($name === '') {
            continue;
        }

        $price = (string) ($item['listPrice'] ?? 0);
        $sku = trim((string) ($item['upcCode'] ?? ''));
        $stock = (int) ($item['inStock'] ?? 0);
        $itemId = (int) ($item['cItemId'] ?? 0);
        $groupId = (int) ($item['cItemGroupId'] ?? 0);
        $rawImages = $itemId > 0 ? ($imagesByItemId[$itemId] ?? []) : [];
        $productImages = [];

        foreach ($rawImages as $position => $image) {
            if (!is_array($image)) {
                continue;
            }

            try {
                $uploaded = upload_remote_image_for_product($cfg['settings'], $image, $name, $itemId, $position + 1);
                if ($uploaded !== null && isset($uploaded['id'])) {
                    $productImages[] = ['id' => $uploaded['id']];
                } elseif ($uploaded !== null && isset($uploaded['src'])) {
                    $productImages[] = ['src' => $uploaded['src']];
                }
            } catch (Throwable $imageError) {
                write_app_log('warning', 'No se pudo preparar imagen para el producto.', [
                    'product' => $name,
                    'item_id' => $itemId,
                    'error' => $imageError->getMessage(),
                ]);
            }
        }

        $product = [
            'name' => $name,
            'type' => 'simple',
            'status' => 'publish',
            'catalog_visibility' => 'visible',
            'description' => $name,
            'short_description' => $name,
            'sku' => $sku,
            'regular_price' => $price,
            'manage_stock' => true,
            'stock_quantity' => $stock,
            'stock_status' => $stock > 0 ? 'instock' : 'outofstock',
            'images' => $productImages,
        ];

        $wooCategoryId = $categoryIdsByGroupId[$groupId] ?? 0;
        if ($wooCategoryId > 0) {
            $product['categories'] = [
                ['id' => $wooCategoryId],
            ];
        }

        if ($syncTagId > 0) {
            $product['tags'] = [
                ['id' => $syncTagId],
            ];
        }

        $products[] = $product;
    }

    return $products;
}

function create_products_batch(array $settings, array $products): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $ck = trim((string) ($settings['WordPress Client Key'] ?? ''));
    $cs = trim((string) ($settings['WordPress Client Secret'] ?? ''));
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products/batch';

    $auth = base64_encode($ck . ':' . $cs);
    $headers = [
        'Content-Type: application/json',
        'Authorization: Basic ' . $auth,
    ];

    $resp = curl_json_request('POST', $apiUrl, $headers, ['create' => $products]);
    if ($resp['status'] !== 200 && $resp['status'] !== 201) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return $resp['data'];
}

function create_single_product(array $settings, array $product): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $ck = trim((string) ($settings['WordPress Client Key'] ?? ''));
    $cs = trim((string) ($settings['WordPress Client Secret'] ?? ''));
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products';

    $auth = base64_encode($ck . ':' . $cs);
    $headers = [
        'Content-Type: application/json',
        'Authorization: Basic ' . $auth,
    ];

    $resp = curl_json_request('POST', $apiUrl, $headers, $product);
    if ($resp['status'] !== 200 && $resp['status'] !== 201) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return $resp['data'];
}

function update_single_product(array $settings, int $productId, array $product): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products/' . $productId;

    $resp = curl_json_request('PUT', $apiUrl, $headers, $product);
    if ($resp['status'] !== 200 && $resp['status'] !== 201) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return $resp['data'];
}

function woo_auth_headers(array $settings): array {
    $ck = trim((string) ($settings['WordPress Client Key'] ?? ''));
    $cs = trim((string) ($settings['WordPress Client Secret'] ?? ''));
    $auth = base64_encode($ck . ':' . $cs);

    return [
        'Content-Type: application/json',
        'Authorization: Basic ' . $auth,
    ];
}

function find_product_by_sku(array $settings, string $sku): ?array {
    $sku = trim($sku);
    if ($sku === '') {
        return null;
    }

    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $query = http_build_query([
        'sku' => $sku,
        'per_page' => 1,
    ]);
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products?' . $query;
    $resp = curl_json_request('GET', $apiUrl, $headers);
    if ($resp['status'] !== 200) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    if (!is_array($resp['data']) || count($resp['data']) === 0 || !is_array($resp['data'][0])) {
        return null;
    }

    return $resp['data'][0];
}

function list_product_categories(array $settings): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $categories = [];
    $page = 1;

    while (true) {
        $query = http_build_query([
            'per_page' => 100,
            'page' => $page,
            'hide_empty' => 'false',
        ]);
        $apiUrl = $baseUrl . '/wp-json/wc/v3/products/categories?' . $query;
        $resp = curl_json_request('GET', $apiUrl, $headers);
        if ($resp['status'] !== 200) {
            $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
            throw new RuntimeException((string) $msg);
        }
        if (!is_array($resp['data'])) {
            throw new RuntimeException('Respuesta WooCommerce inesperada al listar categorías.');
        }

        $pageItems = $resp['data'];
        foreach ($pageItems as $category) {
            if (is_array($category)) {
                $categories[] = $category;
            }
        }
        if (count($pageItems) < 100) {
            break;
        }
        $page++;
    }

    return $categories;
}

function delete_product_category(array $settings, int $categoryId): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products/categories/' . $categoryId . '?force=true';

    $resp = curl_json_request('DELETE', $apiUrl, $headers);
    if ($resp['status'] !== 200 && $resp['status'] !== 204) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return is_array($resp['data']) ? $resp['data'] : [];
}

function create_product_category(array $settings, string $name): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products/categories';

    $resp = curl_json_request('POST', $apiUrl, $headers, ['name' => $name]);
    if ($resp['status'] !== 200 && $resp['status'] !== 201) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return $resp['data'];
}

function list_product_tags(array $settings): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $tags = [];
    $page = 1;

    while (true) {
        $query = http_build_query([
            'per_page' => 100,
            'page' => $page,
        ]);
        $apiUrl = $baseUrl . '/wp-json/wc/v3/products/tags?' . $query;
        $resp = curl_json_request('GET', $apiUrl, $headers);
        if ($resp['status'] !== 200) {
            $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
            throw new RuntimeException((string) $msg);
        }
        if (!is_array($resp['data'])) {
            throw new RuntimeException('Respuesta WooCommerce inesperada al listar tags.');
        }

        $pageItems = $resp['data'];
        foreach ($pageItems as $tag) {
            if (is_array($tag)) {
                $tags[] = $tag;
            }
        }
        if (count($pageItems) < 100) {
            break;
        }
        $page++;
    }

    return $tags;
}

function create_product_tag(array $settings, string $name): array {
    $baseUrl = normalize_wp_url((string) ($settings['WordPress URL'] ?? ''));
    $headers = woo_auth_headers($settings);
    $apiUrl = $baseUrl . '/wp-json/wc/v3/products/tags';

    $resp = curl_json_request('POST', $apiUrl, $headers, ['name' => $name]);
    if ($resp['status'] !== 200 && $resp['status'] !== 201) {
        $msg = $resp['data']['message'] ?? "WooCommerce error {$resp['status']}";
        throw new RuntimeException((string) $msg);
    }

    return $resp['data'];
}

function ensure_product_tag(array $settings, string $name): array {
    $targetKey = category_name_key($name);
    foreach (list_product_tags($settings) as $tag) {
        if (!is_array($tag)) {
            continue;
        }

        $tagName = trim((string) ($tag['name'] ?? ''));
        $tagId = (int) ($tag['id'] ?? 0);
        if ($tagId > 0 && category_name_key($tagName) === $targetKey) {
            return $tag;
        }
    }

    return create_product_tag($settings, $name);
}

function replace_product_categories(array $settings, array $categoryNames): array {
    if (count($categoryNames) === 0) {
        throw new RuntimeException('OIS no devolvió categorías válidas en ResultItemGroups.');
    }

    $existing = list_product_categories($settings);
    $deleted = [];
    $deleteErrors = [];
    foreach ($existing as $category) {
        $categoryId = (int) ($category['id'] ?? 0);
        $categoryName = (string) ($category['name'] ?? '');
        if ($categoryId <= 0) {
            continue;
        }

        try {
            $deleted[] = delete_product_category($settings, $categoryId);
        } catch (Throwable $e) {
            $deleteErrors[] = [
                'id' => $categoryId,
                'name' => $categoryName,
                'message' => $e->getMessage(),
            ];
        }
    }

    $created = [];
    $createErrors = [];
    foreach ($categoryNames as $name) {
        try {
            $created[] = create_product_category($settings, $name);
        } catch (Throwable $e) {
            $createErrors[] = [
                'name' => $name,
                'message' => $e->getMessage(),
            ];
        }
    }

    return [
        'deleted' => $deleted,
        'created' => $created,
        'delete_errors' => $deleteErrors,
        'create_errors' => $createErrors,
    ];
}

function check_remote_asset(string $url): array {
    $ch = curl_init($url);
    if ($ch === false) {
        return ['ok' => false, 'status' => 0];
    }

    curl_setopt_array($ch, [
        CURLOPT_NOBODY => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_HTTPHEADER => [
            'User-Agent: WooConnectorPHP/1.0',
        ],
    ]);

    $result = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    if ($result === false) {
        curl_close($ch);
        return ['ok' => false, 'status' => 0];
    }

    curl_close($ch);
    return [
        'ok' => $status >= 200 && $status < 300,
        'status' => $status,
    ];
}

function filter_reachable_images(array $product): array {
    $images = $product['images'] ?? [];
    $validImages = [];

    foreach ($images as $image) {
        if (!is_array($image)) {
            continue;
        }
        $mediaId = (int) ($image['id'] ?? 0);
        if ($mediaId > 0) {
            $validImages[] = ['id' => $mediaId];
            continue;
        }
        $src = trim((string) ($image['src'] ?? ''));
        if ($src === '') {
            continue;
        }

        $check = check_remote_asset($src);
        if ($check['ok']) {
            $validImages[] = ['src' => $src];
        } else {
            write_app_log('warning', 'Imagen pública no accesible antes de crear producto.', [
                'product' => $product['name'] ?? '',
                'sku' => $product['sku'] ?? '',
                'src' => $src,
                'http_status' => $check['status'],
            ]);
        }
    }

    $product['images'] = $validImages;
    return $product;
}

function normalize_product_for_change_hash(array $product): array {
    $categories = [];
    foreach (($product['categories'] ?? []) as $category) {
        if (is_array($category)) {
            $id = (int) ($category['id'] ?? 0);
            if ($id > 0) {
                $categories[] = $id;
            }
        }
    }
    sort($categories);

    $tags = [];
    foreach (($product['tags'] ?? []) as $tag) {
        if (is_array($tag)) {
            $id = (int) ($tag['id'] ?? 0);
            if ($id > 0) {
                $tags[] = $id;
            }
        }
    }
    sort($tags);

    $images = [];
    foreach (($product['images'] ?? []) as $image) {
        if (!is_array($image)) {
            continue;
        }
        $src = trim((string) ($image['src'] ?? ''));
        if ($src !== '') {
            $images[] = $src;
            continue;
        }
        $id = (int) ($image['id'] ?? 0);
        if ($id > 0) {
            $images[] = 'media:' . $id;
        }
    }

    return [
        'name' => trim((string) ($product['name'] ?? '')),
        'type' => (string) ($product['type'] ?? 'simple'),
        'status' => (string) ($product['status'] ?? 'publish'),
        'catalog_visibility' => (string) ($product['catalog_visibility'] ?? 'visible'),
        'description' => trim((string) ($product['description'] ?? '')),
        'short_description' => trim((string) ($product['short_description'] ?? '')),
        'sku' => trim((string) ($product['sku'] ?? '')),
        'regular_price' => number_format((float) ($product['regular_price'] ?? 0), 2, '.', ''),
        'manage_stock' => (bool) ($product['manage_stock'] ?? false),
        'stock_quantity' => (int) ($product['stock_quantity'] ?? 0),
        'stock_status' => (string) ($product['stock_status'] ?? ''),
        'categories' => $categories,
        'tags' => $tags,
        'images' => $images,
    ];
}

function product_change_hash(array $product): string {
    $json = json_encode(normalize_product_for_change_hash($product), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        return '';
    }

    return hash('sha256', $json);
}

function product_meta_value(array $product, string $key): string {
    foreach (($product['meta_data'] ?? []) as $meta) {
        if (!is_array($meta)) {
            continue;
        }
        if ((string) ($meta['key'] ?? '') === $key) {
            return (string) ($meta['value'] ?? '');
        }
    }

    return '';
}

function product_has_changes(array $existingProduct, array $desiredProduct): bool {
    $expectedHash = product_change_hash($desiredProduct);
    if ($expectedHash !== '' && product_meta_value($existingProduct, OIS_SYNC_HASH_META_KEY) === $expectedHash) {
        return false;
    }

    $existingComparable = [
        'name' => $existingProduct['name'] ?? '',
        'type' => $existingProduct['type'] ?? 'simple',
        'status' => $existingProduct['status'] ?? 'publish',
        'catalog_visibility' => $existingProduct['catalog_visibility'] ?? 'visible',
        'description' => $existingProduct['description'] ?? '',
        'short_description' => $existingProduct['short_description'] ?? '',
        'sku' => $existingProduct['sku'] ?? '',
        'regular_price' => $existingProduct['regular_price'] ?? '0',
        'manage_stock' => $existingProduct['manage_stock'] ?? false,
        'stock_quantity' => $existingProduct['stock_quantity'] ?? 0,
        'stock_status' => $existingProduct['stock_status'] ?? '',
        'categories' => array_map(
            static fn(array $category): array => ['id' => (int) ($category['id'] ?? 0)],
            array_filter($existingProduct['categories'] ?? [], 'is_array')
        ),
        'tags' => array_map(
            static fn(array $tag): array => ['id' => (int) ($tag['id'] ?? 0)],
            array_filter($existingProduct['tags'] ?? [], 'is_array')
        ),
        'images' => array_map(
            static fn(array $image): array => ['src' => (string) ($image['src'] ?? '')],
            array_filter($existingProduct['images'] ?? [], 'is_array')
        ),
    ];

    return normalize_product_for_change_hash($existingComparable) !== normalize_product_for_change_hash($desiredProduct);
}

function with_sync_hash_meta(array $product): array {
    $hash = product_change_hash($product);
    if ($hash === '') {
        return $product;
    }

    $metaData = [];
    foreach (($product['meta_data'] ?? []) as $meta) {
        if (is_array($meta) && (string) ($meta['key'] ?? '') !== OIS_SYNC_HASH_META_KEY) {
            $metaData[] = $meta;
        }
    }
    $metaData[] = [
        'key' => OIS_SYNC_HASH_META_KEY,
        'value' => $hash,
    ];

    $product['meta_data'] = $metaData;
    return $product;
}

function summarize_created_products(array $created): array {
    $details = [];
    foreach ($created as $row) {
        if (!is_array($row) || (int) ($row['id'] ?? 0) <= 0) {
            continue;
        }

        $details[] = [
            'id' => $row['id'],
            'name' => $row['name'] ?? '',
            'sku' => $row['sku'] ?? '',
            'status' => $row['status'] ?? '',
            'permalink' => $row['permalink'] ?? '',
        ];
    }

    return $details;
}

function summarize_errors(array $created): array {
    $errors = [];
    foreach ($created as $row) {
        if (!is_array($row) || (int) ($row['id'] ?? 0) > 0) {
            continue;
        }

        $errors[] = [
            'name' => $row['name'] ?? '',
            'sku' => $row['sku'] ?? '',
            'message' => $row['error']['message'] ?? 'Error desconocido',
            'code' => $row['error']['code'] ?? '',
        ];
    }

    return $errors;
}

function is_image_upload_error(array $row): bool {
    $code = (string) ($row['error']['code'] ?? '');
    $message = strtolower((string) ($row['error']['message'] ?? ''));

    if ($code === 'woocommerce_product_image_upload_error') {
        return true;
    }

    return str_contains($message, 'remote image')
        || str_contains($message, 'invalid image')
        || str_contains($message, 'upload this file type')
        || str_contains($message, 'not found');
}

function retry_products_without_images(array $settings, array $products, array $created): array {
    $retried = [];
    $recovered = [];
    $remainingErrors = [];

    foreach ($created as $index => $row) {
        $product = $products[$index] ?? null;
        if (!is_array($product)) {
            if (is_array($row)) {
                $remainingErrors[] = $row;
            }
            continue;
        }

        if (is_array($row) && (int) ($row['id'] ?? 0) > 0) {
            $recovered[] = $row;
            continue;
        }

        if (is_array($row) && is_image_upload_error($row)) {
            $retryProduct = $product;
            $retryProduct['images'] = [];
            try {
                $retryResponse = create_single_product($settings, $retryProduct);
                $recovered[] = $retryResponse;
                $retried[] = [
                    'name' => $retryResponse['name'] ?? ($product['name'] ?? ''),
                    'sku' => $retryResponse['sku'] ?? ($product['sku'] ?? ''),
                    'reason' => $row['error']['message'] ?? 'Error de imagen',
                    'recovered_without_images' => true,
                    'id' => $retryResponse['id'] ?? 0,
                    'permalink' => $retryResponse['permalink'] ?? '',
                ];
                write_app_log('warning', 'Producto recuperado sin imágenes tras error de upload.', [
                    'name' => $product['name'] ?? '',
                    'sku' => $product['sku'] ?? '',
                    'error' => $row['error']['message'] ?? '',
                    'created_id' => $retryResponse['id'] ?? 0,
                ]);
                continue;
            } catch (Throwable $retryError) {
                $row['retry_error'] = [
                    'message' => $retryError->getMessage(),
                ];
                write_app_log('error', 'Falló reintento de producto sin imágenes.', [
                    'name' => $product['name'] ?? '',
                    'sku' => $product['sku'] ?? '',
                    'original_error' => $row['error']['message'] ?? '',
                    'retry_error' => $retryError->getMessage(),
                ]);
            }
        }

        if (is_array($row)) {
            $remainingErrors[] = $row;
        }
    }

    return [
        'created' => $recovered,
        'errors' => $remainingErrors,
        'retried_without_images' => $retried,
    ];
}

function sync_products_individually(array $settings, array $products): array {
    $createdProducts = [];
    $updatedProducts = [];
    $skippedProducts = [];
    $errorDetails = [];
    $retriedWithoutImages = [];

    foreach ($products as $product) {
        if (!is_array($product)) {
            continue;
        }

        $preparedProduct = filter_reachable_images($product);
        $sku = trim((string) ($preparedProduct['sku'] ?? ''));
        if ($sku === '') {
            $errorDetails[] = [
                'name' => $preparedProduct['name'] ?? '',
                'sku' => '',
                'message' => 'Producto omitido: no tiene SKU/UPC para identificarlo sin duplicados.',
                'code' => 'missing_sku',
            ];
            write_app_log('warning', 'Producto omitido por falta de SKU.', [
                'name' => $preparedProduct['name'] ?? '',
            ]);
            continue;
        }

        $preparedProduct = with_sync_hash_meta($preparedProduct);
        $existingProduct = null;
        $action = 'create';

        try {
            $existingProduct = find_product_by_sku($settings, $sku);
            $action = $existingProduct === null ? 'create' : 'update';

            write_app_log('info', $action === 'create' ? 'Creando producto en WooCommerce.' : 'Revisando producto existente en WooCommerce.', [
                'name' => $preparedProduct['name'] ?? '',
                'sku' => $sku,
                'existing_id' => $existingProduct['id'] ?? null,
                'images' => array_map(
                    static fn(array $image): string => isset($image['id'])
                        ? ('media:' . (string) $image['id'])
                        : (string) ($image['src'] ?? ''),
                    array_filter($preparedProduct['images'] ?? [], 'is_array')
                ),
            ]);

            if ($existingProduct === null) {
                $createdProducts[] = create_single_product($settings, $preparedProduct);
                continue;
            }

            $existingId = (int) ($existingProduct['id'] ?? 0);
            if ($existingId <= 0) {
                throw new RuntimeException('WooCommerce devolvió un producto existente sin ID válido.');
            }

            if (!product_has_changes($existingProduct, $preparedProduct)) {
                $skippedProducts[] = [
                    'id' => $existingId,
                    'name' => $existingProduct['name'] ?? ($preparedProduct['name'] ?? ''),
                    'sku' => $sku,
                    'reason' => 'sin cambios',
                    'permalink' => $existingProduct['permalink'] ?? '',
                ];
                write_app_log('info', 'Producto omitido porque no tiene cambios.', [
                    'name' => $preparedProduct['name'] ?? '',
                    'sku' => $sku,
                    'id' => $existingId,
                ]);
                continue;
            }

            $updatedProducts[] = update_single_product($settings, $existingId, $preparedProduct);
            continue;
        } catch (Throwable $syncError) {
            $message = $syncError->getMessage();
            write_app_log('warning', 'Falló sincronización inicial del producto.', [
                'name' => $preparedProduct['name'] ?? '',
                'sku' => $sku,
                'action' => $action,
                'error' => $message,
            ]);

            if ($existingProduct === null && count($preparedProduct['images'] ?? []) > 0 && is_image_upload_error([
                'error' => ['message' => $message],
            ])) {
                $retryProduct = $preparedProduct;
                $retryProduct['images'] = [];
                $retryProduct = with_sync_hash_meta($retryProduct);

                try {
                    $retryResponse = create_single_product($settings, $retryProduct);
                    $createdProducts[] = $retryResponse;
                    $retriedWithoutImages[] = [
                        'name' => $retryResponse['name'] ?? ($preparedProduct['name'] ?? ''),
                        'sku' => $retryResponse['sku'] ?? ($preparedProduct['sku'] ?? ''),
                        'reason' => $message,
                        'recovered_without_images' => true,
                        'id' => $retryResponse['id'] ?? 0,
                        'permalink' => $retryResponse['permalink'] ?? '',
                    ];
                    write_app_log('warning', 'Producto recuperado sin imágenes tras error de upload.', [
                        'name' => $preparedProduct['name'] ?? '',
                        'sku' => $sku,
                        'error' => $message,
                        'created_id' => $retryResponse['id'] ?? 0,
                    ]);
                    continue;
                } catch (Throwable $retryError) {
                    $message .= ' | Retry sin imágenes: ' . $retryError->getMessage();
                    write_app_log('error', 'Falló reintento del producto sin imágenes.', [
                        'name' => $preparedProduct['name'] ?? '',
                        'sku' => $sku,
                        'error' => $retryError->getMessage(),
                    ]);
                }
            }

            $errorDetails[] = [
                'name' => $preparedProduct['name'] ?? '',
                'sku' => $sku,
                'message' => $message,
                'code' => '',
            ];
        }
    }

    return [
        'created_products' => $createdProducts,
        'updated_products' => $updatedProducts,
        'skipped_products' => $skippedProducts,
        'error_details' => $errorDetails,
        'retried_without_images' => $retriedWithoutImages,
    ];
}

function test_ois_connection(): array {
    $cfg = load_config();
    validate_settings_required($cfg['settings']);

    $targetStore = normalize_wp_url((string) ($cfg['settings']['WordPress URL'] ?? ''));
    write_app_log('info', 'Probando conexión OIS.', [
        'target_store' => $targetStore,
    ]);

    $items = fetch_ois_items($cfg['settings']);
    $count = count($items);
    $sample = [];
    foreach (array_slice($items, 0, 3) as $item) {
        if (!is_array($item)) {
            continue;
        }
        $sample[] = [
            'cItemId' => $item['cItemId'] ?? null,
            'name' => $item['name'] ?? '',
            'sku' => $item['upcCode'] ?? '',
        ];
    }

    write_app_log('info', 'Prueba de conexión completada.', [
        'target_store' => $targetStore,
        'received' => $count,
        'sample' => $sample,
    ]);

    return [
        'message' => $count > 0
            ? "Conexión correcta. OIS devolvió {$count} producto(s)."
            : 'Conexión correcta, pero OIS no devolvió productos.',
        'summary' => [
            'received' => $count,
            'has_results' => $count > 0,
            'target_store' => $targetStore,
        ],
        'sample_products' => $sample,
    ];
}

function run_category_sync(): array {
    $cfg = load_config();
    validate_settings_required($cfg['settings']);

    $targetStore = normalize_wp_url((string) ($cfg['settings']['WordPress URL'] ?? ''));
    write_app_log('warning', 'Iniciando reemplazo de categorías WooCommerce.', [
        'target_store' => $targetStore,
    ]);

    $groups = fetch_ois_item_groups($cfg['settings']);
    $categoryNames = extract_category_names_from_groups($groups);
    $result = replace_product_categories($cfg['settings'], $categoryNames);

    $createdDetails = [];
    foreach ($result['created'] as $category) {
        if (!is_array($category)) {
            continue;
        }
        $createdDetails[] = [
            'id' => $category['id'] ?? null,
            'name' => $category['name'] ?? '',
            'slug' => $category['slug'] ?? '',
        ];
    }

    $deletedCount = count($result['deleted']);
    $createdCount = count($createdDetails);
    $deleteErrorCount = count($result['delete_errors']);
    $createErrorCount = count($result['create_errors']);

    write_app_log('info', 'Reemplazo de categorías finalizado.', [
        'target_store' => $targetStore,
        'received_groups' => count($groups),
        'requested_categories' => count($categoryNames),
        'deleted' => $deletedCount,
        'created' => $createdCount,
        'delete_errors' => $deleteErrorCount,
        'create_errors' => $createErrorCount,
    ]);

    return [
        'message' => 'Categorías procesadas',
        'summary' => [
            'target_store' => $targetStore,
            'received' => count($groups),
            'requested' => count($categoryNames),
            'deleted' => $deletedCount,
            'created' => $createdCount,
            'delete_errors' => $deleteErrorCount,
            'create_errors' => $createErrorCount,
        ],
        'created_categories' => $createdDetails,
        'delete_errors' => $result['delete_errors'],
        'create_errors' => $result['create_errors'],
    ];
}

function run_sync(string $mode = 'new', bool $persistMode = true): array {
    $cfg = load_config();
    $targetStore = normalize_wp_url((string) ($cfg['settings']['WordPress URL'] ?? ''));

    if ($mode !== 'new' && $mode !== 'all') {
        throw new InvalidArgumentException("Mode inválido. Usa 'new' o 'all'.");
    }

    if ($persistMode) {
        $cfg['sync']['mode'] = $mode;
        save_config($cfg);
    }

    if ($mode === 'all') {
        write_app_log('warning', "Sync cancelada: modo 'all' no implementado.", [
            'mode' => $mode,
            'target_store' => $targetStore,
        ]);
        return [
            'message' => "Modo 'borrar todo' aún no implementado.",
            'result' => null,
        ];
    }

    validate_settings_required($cfg['settings']);
    write_app_log('info', 'Iniciando sincronización.', [
        'mode' => $mode,
        'target_store' => $targetStore,
    ]);

    $items = fetch_ois_items($cfg['settings']);
    $groups = fetch_ois_item_groups($cfg['settings']);
    $wooCategories = list_product_categories($cfg['settings']);
    $categoryIdsByGroupId = build_category_ids_by_group_id($groups, $wooCategories);
    $syncTag = ensure_product_tag($cfg['settings'], OIS_SYNC_TAG_NAME);
    $syncTagId = (int) ($syncTag['id'] ?? 0);
    $imagesByItemId = fetch_ois_images($cfg['settings']);
    $products = map_to_woo_products($items, $imagesByItemId, $categoryIdsByGroupId, $syncTagId);
    if (count($products) === 0) {
        throw new RuntimeException('OIS no devolvió productos válidos.');
    }

    $creationSummary = sync_products_individually($cfg['settings'], $products);
    $createdDetails = summarize_created_products($creationSummary['created_products']);
    $updatedDetails = summarize_created_products($creationSummary['updated_products']);
    $skippedDetails = $creationSummary['skipped_products'];
    $errorDetails = $creationSummary['error_details'];
    $created = 0;
    $updated = 0;
    $skipped = count($skippedDetails);
    $errors = 0;
    foreach ($creationSummary['created_products'] as $row) {
        if (is_array($row) && (int) ($row['id'] ?? 0) > 0) {
            $created++;
        }
    }
    foreach ($creationSummary['updated_products'] as $row) {
        if (is_array($row) && (int) ($row['id'] ?? 0) > 0) {
            $updated++;
        }
    }
    foreach ($errorDetails as $row) {
        if (is_array($row)) {
            $errors++;
        }
    }

    $productsWithImages = 0;
    $totalImagesAssigned = 0;
    foreach ($products as $product) {
        $images = $product['images'] ?? [];
        if (is_array($images) && count($images) > 0) {
            $productsWithImages++;
            $totalImagesAssigned += count($images);
        }
    }

    $productsWithCategories = 0;
    foreach ($products as $product) {
        $categories = $product['categories'] ?? [];
        if (is_array($categories) && count($categories) > 0) {
            $productsWithCategories++;
        }
    }

    $productsWithTags = 0;
    foreach ($products as $product) {
        $tags = $product['tags'] ?? [];
        if (is_array($tags) && count($tags) > 0) {
            $productsWithTags++;
        }
    }

    $retriedWithoutImages = $creationSummary['retried_without_images'];
    write_app_log('info', 'Respuesta sincronización WooCommerce recibida.', [
        'target_store' => $targetStore,
        'requested_items' => count($products),
        'created_count' => count($createdDetails),
        'updated_count' => count($updatedDetails),
        'skipped_count' => $skipped,
        'error_count' => count($errorDetails),
        'retried_without_images' => count($retriedWithoutImages),
    ]);

    write_app_log('info', 'Sync finalizada.', [
        'mode' => $mode,
        'target_store' => $targetStore,
        'received' => count($items),
        'mapped' => count($products),
        'ok' => $created + $updated + $skipped,
        'created' => $created,
        'updated' => $updated,
        'skipped' => $skipped,
        'errors' => $errors,
        'products_with_images' => $productsWithImages,
        'images_assigned' => $totalImagesAssigned,
        'category_groups_found' => count($categoryIdsByGroupId),
        'products_with_categories' => $productsWithCategories,
        'sync_tag_id' => $syncTagId,
        'sync_tag_name' => OIS_SYNC_TAG_NAME,
        'products_with_tags' => $productsWithTags,
        'created_products' => $createdDetails,
        'updated_products' => $updatedDetails,
        'skipped_products' => $skippedDetails,
        'error_details' => $errorDetails,
        'retried_without_images' => $retriedWithoutImages,
    ]);

    return [
        'message' => 'Sincronización completada',
        'summary' => [
            'ok' => $created + $updated + $skipped,
            'created' => $created,
            'updated' => $updated,
            'skipped' => $skipped,
            'errors' => $errors,
            'mapped' => count($products),
            'received' => count($items),
            'limit' => SYNC_LIMIT,
            'products_with_images' => $productsWithImages,
            'images_assigned' => $totalImagesAssigned,
            'category_groups_found' => count($categoryIdsByGroupId),
            'products_with_categories' => $productsWithCategories,
            'sync_tag_id' => $syncTagId,
            'sync_tag_name' => OIS_SYNC_TAG_NAME,
            'products_with_tags' => $productsWithTags,
            'target_store' => $targetStore,
            'retried_without_images' => count($retriedWithoutImages),
        ],
        'created_products' => $createdDetails,
        'updated_products' => $updatedDetails,
        'skipped_products' => $skippedDetails,
        'error_details' => $errorDetails,
        'retried_without_images' => $retriedWithoutImages,
        'result' => [
            'create' => $creationSummary['created_products'],
            'update' => $creationSummary['updated_products'],
            'skipped' => $skippedDetails,
            'errors' => $errorDetails,
        ],
    ];
}
