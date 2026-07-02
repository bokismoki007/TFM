from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if dictionary is None:
        return None
    try:
        return dictionary.get(key)
    except (AttributeError, TypeError):
        try:
            return dictionary[key]
        except (KeyError, TypeError, IndexError):
            return None

@register.filter
def get_first_key(dictionary):
    if dictionary and hasattr(dictionary, 'keys'):
        keys = list(dictionary.keys())
        return keys[0] if keys else None
    return None

@register.filter
def get_first_item(list_obj):
    if list_obj and hasattr(list_obj, '__getitem__'):
        try:
            return list_obj[0]
        except (IndexError, TypeError):
            return None
    return None

@register.filter
def to_list(dict_keys):
    if dict_keys is None:
        return []
    if hasattr(dict_keys, 'keys'):
        return list(dict_keys.keys())
    if hasattr(dict_keys, '__iter__'):
        return list(dict_keys)
    return []