


def rejection(rule):
    cues = ' '.join(c.casefold() for p in rule['positive'] for c in p['all'])
    cause = rule['cause']
    if cause == 'pod_network_delay' and not any(marker in cues for marker in (
            'netem', 'qdisc', 'network delay injected', 'traffic shaping')):
        return 'Require a direct delay mechanism; validation code and sidecar CPU limits are insufficient.'
    if cause.endswith('dns_resolution_failure') or cause == 'image_registry_dns_failure':
        if not any(marker in cues for marker in (
                'no such host', 'unknownhostexception', 'name resolution',
                'name or service not known', 'could not resolve', 'nxdomain')):
            return 'Require an explicit name-resolution error; crashes and error counts are insufficient.'
    if cause == 'missing_image_pull_secret' and not any(marker in cues for marker in (
            'failedtoretrieveimagepullsecret', 'secret "', 'secret not found')):
        return 'Authorization failure does not distinguish missing credentials from invalid credentials.'
    if cause == 'missing_secret_binding' and 'not found' not in cues:
        return 'Config error plus a Secret reference does not prove the referenced Secret is missing.'
    if cause == 'mysql_invalid_port' and all(
            cue in {'communications link failure', 'jdbcconnectionexception'}
            for p in rule['positive'] for cue in (c.casefold() for c in p['all'])):
        return 'Generic connection failure and absence of DNS errors do not establish an incorrect port.'
    if cause.startswith('namespace_') and cause.endswith('_quota_exceeded') and 'exceeded quota' not in cues:
        return 'Require an explicit blocked operation exceeding quota, not only a saturated quota.'
    return None
