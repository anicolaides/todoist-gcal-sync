import click
from todoist_gcal_sync.utils.setup.helper import self_cleanup


@click.group()
def cli():
    pass


@click.command(help='Starts the daemon')
def start():
    pass


@click.command(help='Stops the daemon')
def stop():
    pass


@click.command(help='Deletes the calendars and the database of the app')
def cleanup():
    self_cleanup()


@click.command(help='Install the systemd script for Ubuntu')
def systemd():
    pass


@click.command(help='Supply project names to be excluded.')
def exclude_proj():
    pass


cli.add_command(start)
cli.add_command(stop)
cli.add_command(cleanup)
cli.add_command(systemd)

if __name__ == '__main__':
    cli()
