import click

def secho(*args, **kwargs):
    pass

click.secho = secho
click.echo = secho
