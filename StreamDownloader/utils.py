
def FormatFileSize(size):
    'Formats the file size into a human readable format.'
    for suffix in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024.0:
            if suffix in ('GB', 'TB'):
                return '{0:3.2f} {1}'.format(size, suffix)
            return '{0:3.1f} {1}'.format(size, suffix)
        size /= 1024.0

def FormatSeconds(seconds):
    (mins, secs) = divmod(seconds, 60)
    (hours, mins) = divmod(mins, 60)
    if hours > 99:
        return '--:--:--'
    if hours == 0:
        return '%02d:%02d' % (mins, secs)
    else:
        return '%02d:%02d:%02d' % (hours, mins, secs)

def FormatPercent(percent):
    return '%0.2f%%' % percent

