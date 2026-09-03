from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """
    Standard DRF Pagination for list endpoints supporting ?page=X&page_size=Y.
    """
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'
