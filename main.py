# import standard libraries
import cProfile
import datetime
import getopt
import logging
import math
import os
import sys
import traceback
import typing
from datetime import datetime
# import local files
import feature_extractors.Extractor
import Request
import utils
from config import settings
from managers.ExportManager import ExportManager
from feature_extractors.CrystalExtractor import CrystalExtractor
from feature_extractors.WaveExtractor import WaveExtractor
from schemas.Schema import Schema

## Function to print a "help" listing for the export tool.
#  Hopefully not needed too often, if at all.
#  Just nice to have on hand, in case we ever need it.
def showHelp():
    width = 30
    print(width*"*")
    print("usage: <python> main.py <cmd> [<args>]")
    print("")
    print("<python> is your python command.")
    print("<cmd>    is one of the available commands:")
    print("         - export")
    print("         - export_month")
    print("         - export_all_months")
    print("         - info")
    print("         - readme")
    print("         - help")
    print("[<args>] are the arguments for the command:")
    print("         - export: game_id, [start_date, end_date]")
    print("             game_id    = id of game to export")
    print("             start_date = beginning date for export, in form mm/dd/yyyy (default=first day of current month)")
    print("             end_date   = ending date for export, in form mm/dd/yyyy (default=current day)")
    print("         - export_month: game_id, [month_year]")
    print("             game_id    = id of game to export")
    print("             month_year = month (and year) to export, in form mm/yyyy (default=current month)")
    print("         - export_all_months: game_id")
    print("             game_id    = id of game to export")
    print("         - info: game_id")
    print("             game_id    = id of game whose info should be shown")
    print("         - readme: game_id")
    print("             game_id    = id of game whose readme should be generated")
    print("         - help: *None*")
    print(width*"*")


## Function to handle execution of export code. This is the main intended use of
#  the program.
def runExport(monthly: bool = False, all_data: bool = False):
    # retrieve game id
    if num_args > 2:
        game_id = args[2]
    else:
        showHelp()
        return
    # retrieve/calculate date range.
    start_date: datetime
    end_date: datetime
    # If we want to export all data for a given month, calculate a date range.
    if monthly is True:
        if all_data is True:
            utils.Logger.toStdOut(f"Exporting all months of {game_id}...", logging.DEBUG)
            _execAllMonthExport(game_id=game_id)
            utils.Logger.toStdOut(f"Done with {game_id}.", logging.DEBUG)
        else:
            month_year: typing.List[int]
            if num_args > 3:
                month_year_str = args[3].split("/")
                month_year = [int(month_year_str[0]), int(month_year_str[1])]
            else:
                today   = datetime.now()
                month_year = [today.month, today.year]
            utils.Logger.toStdOut(f"Exporting {month_year[0]}/{month_year[1]} data for {game_id}...", logging.DEBUG)
            _execMonthExport(game_id=game_id, month=month_year[0], year=month_year[1])
            utils.Logger.toStdOut(f"Done with {game_id}.", logging.DEBUG)
    # Otherwise, create date range from given pair of dates.
    else:
        today   = datetime.now()
        start_date = datetime.strptime(args[3], "%m/%d/%Y") if num_args > 4 \
                else today
        start_date = start_date.replace(hour=0, minute=0, second=0)
        end_date   = datetime.strptime(args[4], "%m/%d/%Y") if num_args > 4 \
                else today
        end_date = end_date.replace(hour=23, minute=59, second=59)
        utils.Logger.toStdOut(f"Exporting from {str(start_date)} to {str(end_date)} of data for {game_id}...", logging.DEBUG)
        _execExport(game_id, start_date, end_date)
        utils.Logger.toStdOut(f"Done with {game_id}.", logging.DEBUG)

def _execAllMonthExport(game_id):
    tunnel, db  = utils.SQL.prepareDB(db_settings=db_settings, ssh_settings=ssh_settings)
    first_entry = utils.SQL.SELECT(cursor=db.cursor(), db_name=db_settings["DB_NAME_DATA"], table=db_settings["table"],
                                    columns=["server_time"], filter=f"app_id='{game_id}'",
                                    sort_columns=["server_time"], sort_direction="ASC", limit=1)
    last_entry = utils.SQL.SELECT(cursor=db.cursor(), db_name=db_settings["DB_NAME_DATA"], table=db_settings["table"],
                                    columns=["server_time"], filter=f"app_id='{game_id}'",
                                    sort_columns=["server_time"], sort_direction="DESC", limit=1)
    utils.SQL.disconnectMySQLViaSSH(tunnel=tunnel, db=db)
    # breakpoint()
    first_month = first_entry[0][0].month
    last_month = last_entry[0][0].month
    first_year = first_entry[0][0].year
    last_year = last_entry[0][0].year
    # 1) all months needed in first year.
    #    if all within one year, just do whole month range.
    #    else, go through December.
    end = last_month-1 if first_year == last_year else 12
    for month in range(first_month, end+1):
        _execMonthExport(game_id=game_id, month=month, year=first_year)
    # 2) All months of "interior" years. That is, years completely
    #    contained within the range of years.
    for year in range(first_year+1, last_year):
        for month in range (1, 12+1):
            _execMonthExport(game_id=game_id, month=month, year=year)
    # 3) All months in final year, but only if we didn't already get
    #    it as first year.
    if first_year < last_year:
        for month in range(1, last_month): #note, just to last_month, no +1, since we want to exclude final month
            _execMonthExport(game_id=game_id, month=month, year=last_year)

def _execMonthExport(game_id, month, year):
    from calendar import monthrange
    month_range = monthrange(year, month)
    days_in_month = month_range[1]
    start_date = datetime(year=year, month=month, day=1, hour=0, minute=0, second=0)
    end_date   = datetime(year=year, month=month, day=days_in_month, hour=23, minute=59, second=59)
    _execExport(game_id, start_date, end_date)

def _execExport(game_id, start_date, end_date):
    # Once we have the parameters parsed out, construct the request.
    skip_proc = "--no-extract" in opts
    req = Request.DateRangeRequest(game_id=game_id, start_date=start_date, end_date=end_date, \
                max_sessions=settings["MAX_SESSIONS"], min_moves=settings["MIN_MOVES"], \
                skip_proc=skip_proc)
    start = datetime.now()
    # breakpoint()
    export_manager = ExportManager(game_id=req.game_id, settings=settings)
    try:
        schema = Schema(game_id)
        export_manager.exportFromRequest(request=req, game_schema=schema)
        # cProfile.runctx("feature_exporter.exportFromRequest(request=req)",
                        # {'req':req, 'feature_exporter':feature_exporter}, {})
    except Exception as err:
        utils.Logger.toStdOut(str(err), logging.ERROR)
        utils.Logger.toFile(str(err), logging.ERROR)
        traceback.print_tb(err.__traceback__)
    finally:
        end = datetime.now()
        time_delta = end - start
        minutes = math.floor(time_delta.total_seconds()/60)
        seconds = time_delta.total_seconds() % 60
        print(f"Total time taken: {minutes} min, {seconds} sec")

def ExtractFromFile():
    if num_args > 2:
        file_name = args[2]
    else:
        showHelp()
        return

## Function to print out info on a game from the game's schema.
#  This does a similar function to writeReadme, but is limited to the CSV
#  metadata part (basically what was in the schema, at one time written into
#  the csv's themselves). Further, the output is printed rather than written
#  to file.
def showGameInfo():
    if num_args > 2:
        # try:
            # tunnel, db = utils.SQL.prepareDB(db_settings=db_settings, ssh_settings=ssh_settings)
        game_name = args[2]
        schema = Schema(schema_name=f"{game_name}.json")

        feature_descriptions = {**schema.perlevel_features(), **schema.aggregate_features()}
        print(_genCSVMetadata(game_name=game_name, raw_field_list=schema.db_columns_with_types(),\
                                                        proc_field_list=feature_descriptions))
        # finally:
        #     pass
            # utils.SQL.disconnectMySQLViaSSH(tunnel=tunnel, db=db)
    else:
        print("Error, no game name given!")
        showHelp()

## Function to write out the readme file for a given game.
#  This includes the CSV metadata (data from the schema, originally written into
#  the CSV files themselves), custom readme source, and the global changelog.
#  The readme is placed in the game's data folder.
def writeReadme():
    if num_args > 2:
        try:
            game_name = args[2]
            path = f"./data/{game_name}"
            os.makedirs(name=path, exist_ok=True)
            readme = open(f"{path}/readme.md", "w")
            # Load schema, and write feature & column descriptions to the readme.
            schema = Schema(schema_name=f"{game_name}.json")
            feature_descriptions = {**schema.perlevel_features(), **schema.aggregate_features()}
            readme.write(_genCSVMetadata(game_name=game_name, raw_field_list=schema.db_columns_with_types(),
                                                                proc_field_list=feature_descriptions))
        except Exception as err:
            utils.Logger.toStdOut(str(err), logging.ERROR)
            utils.Logger.toFile(str(err), logging.ERROR)
            traceback.print_tb(err.__traceback__)
        try:
            # Open files with game-specific readme data, and global db changelog.
            readme_src    = open(f"./doc/readme_src/{game_name}_readme_src.md", "r")
            readme.write(readme_src.read())
        except FileNotFoundError as err:
            readme.write("No readme prepared")
            utils.Logger.toStdOut(f"Could not find readme_src for {game_name}", logging.ERROR)
        except Exception as err:
            utils.Logger.toStdOut(str(err), logging.ERROR)
            utils.Logger.toFile(str(err), logging.ERROR)
            traceback.print_tb(err.__traceback__)
        finally:
            readme.write("\n")
        try:
            changelog_src = open("./doc/readme_src/changelog_src.md",           "r")
            readme.write(changelog_src.read())
        except FileNotFoundError as err:
            readme.write("No changelog prepared")
            utils.Logger.toStdOut(f"Could not find changelog_src", logging.ERROR)
        except Exception as err:
            utils.Logger.toStdOut(str(err), logging.ERROR)
            utils.Logger.toFile(str(err), logging.ERROR)
            traceback.print_tb(err.__traceback__)
    else:
        print("Error, no game name given!")
        showHelp()

## Function to generate metadata for a given game.
#  The "fields" are a sort of generalization of columns. Basically, columns which
#  are repeated (say, once per level) all fall under a single field.
#  Columns which are completely unique correspond to individual fields.
#
#  @param game_name         The name of the game for which the csv metadata is being generated.
#  @param raw_field_list    A mapping of raw csv "fields" to descriptions of the fields.
#  @param proc_field_list   A mapping of processed csv features to descriptions of the features.
#  @return                  A string containing metadata for the given game.
def _genCSVMetadata(game_name: str, raw_field_list: typing.Dict[str,str], proc_field_list: typing.Dict[str,str]) -> str:
    raw_field_descriptions = [f"{key} - {raw_field_list[key]}" for key in raw_field_list.keys()]
    proc_field_descriptions = [f"{key} - {proc_field_list[key]}" for key in proc_field_list.keys()]
    raw_field_string = "\n".join(raw_field_descriptions)
    proc_field_string = "\n".join(proc_field_descriptions)
    template_str = \
f"## Field Day Open Game Data \n\
### Retrieved from https://fielddaylab.wisc.edu/opengamedata \n\
### These anonymous data are provided in service of future educational data mining research. \n\
### They are made available under the Creative Commons CCO 1.0 Universal license. \n\
### See https://creativecommons.org/publicdomain/zero/1.0/ \n\
\n\
## Suggested citation: \n\
### Field Day. (2019). Open Educational Game Play Logs - [dataset ID]. Retrieved [today's date] from https://fielddaylab.wisc.edu/opengamedata \n\
\n\
## Game: {game_name} \n\
\n\
## Field Descriptions: \n\
### Raw CSV Columns:\n\
{raw_field_string}\n\
\n\
### Processed Features:\n\
{proc_field_string}\n\
\n"
    return template_str

## This section of code is what runs main itself. Just need something to get it
#  started.
utils.Logger.toStdOut(f"Running {sys.argv[0]}...", logging.INFO)
utils.Logger.toFile(f"Running {sys.argv[0]}...", logging.INFO)
try:
    arg_options = ["help", "no-extract"]
    optupi, args = getopt.gnu_getopt(sys.argv, shortopts="-h", longopts=arg_options)

    opts = {opt[0]: opt[1] for opt in optupi}
    print(f"optupi:{optupi}\nargs:{args}\nopts:{opts}")
    num_args = len(args)
    cmd = args[1] if num_args > 1 else "help"
except getopt.GetoptError as err:
    print(f"Error, invalid option given!\n{err}")
    cmd = "help"
if type(cmd) == str:
    # if we have a real command, load the config file.
    # settings = utils.loadJSONFile("config.json")
    db_settings = settings["db_config"]
    ssh_settings = settings["ssh_config"]

    cmd = cmd.lower()

    if cmd == "export":
        runExport()
    elif cmd == "export_all":
        runExport(all_data=True)
    elif cmd == "export_month":
        runExport(monthly=True)
    elif cmd == "export_all_months":
        runExport(monthly=True, all_data=True)
    elif cmd == "extract":
        ExtractFromFile()
    elif cmd == "info":
        showGameInfo()
    elif cmd == "readme":
        writeReadme()
    elif cmd == "help" or "-h" in opts.keys() or "--help" in opts.keys():
        showHelp()
    else:
        print(f"Invalid Command {cmd}!")
else:
    print("Command is not a string!")
    showHelp()
