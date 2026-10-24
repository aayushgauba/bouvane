from django.utils.cache import add_never_cache_headers


class PrivatePortalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(('/accounts/', '/dashboard/', '/admin/')):
            add_never_cache_headers(response)
            response['X-Robots-Tag'] = 'noindex, nofollow'
            response['Referrer-Policy'] = 'same-origin'
        return response
