# import standard libraries
import cProfile
#import datetime
import getopt
import logging
import sys
import traceback
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from git.remote import FetchInfo

from pandas.io.pytables import Table
# import local files
import utils
from config.config import settings
from interfaces.src.DataInterface import DataInterface
from interfaces.src.CSVInterface import CSVInterface
from interfaces.src.MySQLInterface import MySQLInterface
from interfaces.src.BigQueryInterface import BigQueryInterface
from managers.ExportManager import ExportManager
from managers.Request import Request, ExporterFiles, ExporterRange
from schemas.GameSchema import GameSchema
from schemas.TableSchema import TableSchema
from utils import Logger

## Function to print a "help" listing for the export tool.
#  Hopefully not needed too often, if at all.
#  Just nice to have on hand, in case we ever need it.
def ShowHelp() -> bool:
    width = 30
    print(width*"*")
    print("usage: <python> main.py <cmd> [<args>] [<opt-args>]")
    print("")
    print("<python> is your python command.")
    print("<cmd>    is one of the available commands:")
    print("         - export")
    print("         - export-events")
    print("         - export-session-features")
    print("         - info")
    print("         - readme")
    print("         - help")
    print("[<args>] are the arguments for the command:")
    print("         - export: game_id, [start_date, end_date]")
    print("             game_id    = id of game to export")
    print("             start_date = beginning date for export, in form mm/dd/yyyy (default=first day of current month)")
    print("             end_date   = ending date for export, in form mm/dd/yyyy (default=current day)")
    print("         - export-events: game_id")
    print("             game_id    = id of game to export")
    print("             start_date = beginning date for export, in form mm/dd/yyyy (default=first day of current month)")
    print("             end_date   = ending date for export, in form mm/dd/yyyy (default=current day)")
    print("         - export-session-features: game_id, [month_year]")
    print("             game_id    = id of game to export")
    print("             start_date = beginning date for export, in form mm/dd/yyyy (default=first day of current month)")
    print("             end_date   = ending date for export, in form mm/dd/yyyy (default=current day)")
    print("         - info: game_id")
    print("             game_id    = id of game whose info should be shown")
    print("         - readme: game_id")
    print("             game_id    = id of game whose readme should be generated")
    print("         - help: *None*")
    print("[<opt-args>] are optional arguments, which affect certain commands:")
    print("         --file: specifies a file to export events or features")
    print("         --monthly: with this flag, specify dates by mm/yyyy instead of mm/dd/yyyy.")
    print(width*"*")
    return True

## Function to print out info on a game from the game's schema.
#  This does a similar function to writeReadme, but is limited to the CSV
#  metadata part (basically what was in the schema, at one time written into
#  the csv's themselves). Further, the output is printed rather than written
#  to file.
def ShowGameInfo() -> bool:
    game_schema = GameSchema(schema_name=f"{game_name}.json")
    table_schema = TableSchema(schema_name=f"FIELDDAY_MYSQL.json")

    feature_descriptions = {**game_schema.perlevel_features(), **game_schema.aggregate_features()}
    print(utils.GenCSVMetadata(game_name=game_name, column_list=table_schema.ColumnList(),\
                                                    feature_list=feature_descriptions))
    return True

## Function to write out the readme file for a given game.
#  This includes the CSV metadata (data from the schema, originally written into
#  the CSV files themselves), custom readme source, and the global changelog.
#  The readme is placed in the game's data folder.
def WriteReadme() -> bool:
    path = Path(f"./data") / game_name
    try:
        game_schema = GameSchema(schema_name=f"{game_name}.json")
        table_schema = TableSchema(schema_name=f"FIELDDAY_MYSQL.json")
        utils.GenerateReadme(game_name=game_name, game_schema=game_schema, column_list=table_schema.ColumnList(), path=path)
        Logger.toStdOut(f"Successfully generated a readme for {game_name}.")
        return True
    except Exception as err:
        msg = f"Could not create a readme for {game_name}: {type(err)} {str(err)}"
        Logger.toStdOut(msg, logging.ERROR)
        traceback.print_tb(err.__traceback__)
        Logger.toFile(msg, logging.ERROR)
        return False

## Function to handle execution of export code. This is the main intended use of
#  the program.
def RunExport(events:bool = False, features:bool = False) -> bool:
    ret_val : bool = False

    start = datetime.now()
    req = genRequest(events=events, features=features)
    try:
        if req._interface.IsOpen():
            export_manager = ExportManager(game_id=game_name, settings=settings)
            table_name = settings["GAME_SOURCE_MAP"][game_name]["table"]
            ret_val = export_manager.ExecuteRequest(request=req, game_schema=GameSchema(game_name), table_schema=TableSchema(schema_name=f"{table_name}.json"))
            # cProfile.runctx("feature_exporter.ExportFromSQL(request=req)",
                            # {'req':req, 'feature_exporter':feature_exporter}, {})
    except Exception as err:
        msg = f"{type(err)} {str(err)}"
        Logger.Log(msg, logging.ERROR)
        traceback.print_tb(err.__traceback__)
    finally:
        time_taken = datetime.now() - start
        Logger.Log(f"Total time taken: {time_taken}")
        Logger.Log(f"Done with {game_name}.", logging.INFO)
        return ret_val

def genRequest(events:bool, features:bool) -> Request:
    interface : DataInterface
    range     : ExporterRange
    exporter_files : ExporterFiles
    exporter_files = ExporterFiles(events=events, sessions=features, population=features) 
    supported_vers = GameSchema(schema_name=f"{game_name}.json")['config']['SUPPORTED_VERS']
    if "--file" in opts.keys():
        file_path=opts["--file"]
        ext = file_path.split('.')[-1]
        interface = CSVInterface(game_id=game_name, filepath_or_buffer=file_path, delim="\t" if ext == '.tsv' else ',')
        # retrieve/calculate id range.
        ids = interface.AllIDs()
        range = ExporterRange.FromIDs(ids=ids if ids is not None else [], source=interface, versions=supported_vers)
        # breakpoint()
    else:
        interface_type = settings["GAME_SOURCE_MAP"][game_name]['interface']
        if interface_type == "BigQuery":
            interface = BigQueryInterface(game_id=game_name, settings=settings)
        elif interface_type == "MySQL":
            interface = MySQLInterface(game_id=game_name, settings=settings)
        else:
            raise Exception(f"{interface_type} is not a valid DataInterface type!")
        # retrieve/calculate date range.
        start_date, end_date = getDateRange(args=args, game_id=game_name)
        range = ExporterRange.FromDateRange(date_min=start_date, date_max=end_date, source=interface, versions=supported_vers)
    # Once we have the parameters parsed out, construct the request.
    return Request(interface=interface, range=range, exporter_files=exporter_files)

def getDateRange(args, game_id:str) -> Tuple[datetime, datetime]:
    start_date: datetime
    end_date  : datetime
    today     : datetime = datetime.now()
    # If we want to export all data for a given month, calculate a date range.
    if "--monthly" in opts.keys():
        month: int = today.month
        year:  int = today.year
        if num_args > 3:
            month_year_str = args[3].split("/")
            month = int(month_year_str[0])
            year  = int(month_year_str[1])
        month_range = monthrange(year, month)
        days_in_month = month_range[1]
        start_date = datetime(year=year, month=month, day=1, hour=0, minute=0, second=0)
        end_date   = datetime(year=year, month=month, day=days_in_month, hour=23, minute=59, second=59)
        Logger.toStdOut(f"Exporting {month}/{year} data for {game_id}...", logging.DEBUG)
    # Otherwise, create date range from given pair of dates.
    else:
        start_date = datetime.strptime(args[3], "%m/%d/%Y") if num_args > 3 else today
        start_date = start_date.replace(hour=0, minute=0, second=0)
        end_date   = datetime.strptime(args[4], "%m/%d/%Y") if num_args > 4 else today
        end_date = end_date.replace(hour=23, minute=59, second=59)
        Logger.Log(f"Exporting from {str(start_date)} to {str(end_date)} of data for {game_id}...", logging.INFO)
    return (start_date, end_date)

## This section of code is what runs main itself. Just need something to get it
#  started.
# Logger.Log(f"Running {sys.argv[0]}...", logging.INFO)
opts : Dict[str,str] = {}
args : List[str] = []
try:
    optupi, args = getopt.gnu_getopt(sys.argv, shortopts="-h", longopts=["file=", "help", "monthly"])
    opts = {opt[0]: opt[1] for opt in optupi}
except getopt.GetoptError as err:
    print(f"Error, invalid option given!\n{err}")

num_args = len(args)
cmd = args[1] if num_args > 1 else "help"

if type(cmd) == str:
    cmd = cmd.lower()

    success : bool
    if cmd == "help" or "-h" in opts.keys() or "--help" in opts.keys():
        success = ShowHelp()
    else:
        if num_args > 2:
            game_name = args[2]
        else:
            Logger.Log("No game name given!", logging.WARN)
            success = ShowHelp()
        if cmd == "export":
            success = RunExport(events=True, features=True)
        elif cmd == "export-events":
            success = RunExport(events=True)
        elif cmd == "export-session-features":
            success = RunExport(features=True)
        elif cmd == "info":
            success = ShowGameInfo()
        elif cmd == "readme":
            success = WriteReadme()
        else:
            print(f"Invalid Command {cmd}!")
            success = False
    if not success:
        sys.exit(1)
else:
    Logger.Log("Command is not a string!", logging.ERROR)
    ShowHelp()
