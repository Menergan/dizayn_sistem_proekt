from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

HTTP_REQUESTS = Counter(
    "rental_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "rental_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

RENTAL_CACHE_REQUESTS = Counter(
    "rental_cache_requests_total",
    "Rental Redis cache requests",
    ["result"],
)

RENTAL_CACHE_ERRORS = Counter(
    "rental_cache_errors_total",
    "Rental Redis cache errors",
    ["operation"],
)