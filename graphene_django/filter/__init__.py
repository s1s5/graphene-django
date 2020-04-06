import warnings
from ..utils import DJANGO_FILTER_INSTALLED

if not DJANGO_FILTER_INSTALLED:
    warnings.warn(
        "Use of django filtering requires the django-filter package "
        "be installed. You can do so using `pip install django-filter`",
        ImportWarning,
    )
else:
    from .fields import DjangoFilterConnectionField
    from .filterset import GlobalIDFilter, GlobalIDMultipleChoiceFilter
    from .utils import MultipleOrderingFilter

    __all__ = [
        "DjangoFilterConnectionField",
        "GlobalIDFilter",
        "GlobalIDMultipleChoiceFilter",
        "MultipleOrderingFilter",
    ]
