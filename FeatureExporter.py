## @package DataToCSV.py
#  A package to handle processing of stuff from our database,
#  for export to CSV files.

## import standard libraries
import json
import logging
import math
import os
import typing
from datetime import datetime
## import local files
import utils
from GameTable import GameTable
from ProcManager import ProcManager
from RawManager import RawManager
from Request import Request
from schemas.Schema import Schema
from feature_extractors.WaveExtractor import WaveExtractor
from feature_extractors.CrystalExtractor import CrystalExtractor
from feature_extractors.LakelandExtractor import LakelandExtractor

## @class FeatureExporter
#  A class to export features and raw data, given a Request object.
class FeatureExporter:
    ## Constructor for the FeatureExporter class.
    #  Fairly simple, just saves some data for later use during export.
    #  @param game_id Initial id of game to export
    #                 (this can be changed, if a GameTable with a different id is
    #                  given, but will generate a warning)
    #  @param db      An active database connection
    #  @param settings A dictionary of program settings, some of which are needed for export.
    def __init__(self, game_id: str, db, settings):
        if game_id is None:
            logging.error("Game ID was not given!")
        else:
            self._game_id   = game_id
        self._db       = db
        self._settings = settings

    ## Public function to use for feature extraction and csv export.
    #  Extracts features and exports raw and processed csv's based on the given
    #  request.
    #  @param request A data structure carrying parameters for feature extraction
    #                 and export.
    def exportFromRequest(self, request: Request):
        if request.game_id != self._game_id:
            logging.warn(f"Changing FeatureExporter game from {self._game_id} to {request.game_id}")
            self._game_id = request.game_id
        else:
            game_table: GameTable = GameTable(db=self._db, settings=self._settings, request=request)
            try:
                parse_success: str = self._getAndParseData(request, game_table)
                if parse_success:
                    print(f"Successfully completed request {str(request)}.")
                else:
                    logging.error(f"Could not complete request {str(request)}")
            except Exception as err:
                utils.SQL.server500Error(err)

    ## Private function containing most of the code to handle processing of db
    #  data, and export to files.
    #  @param request    A data structure carrying parameters for feature extraction
    #                    and export
    #  @param game_table A data structure containing information on how the db
    #                    table assiciated with the given game is structured. 
    def _getAndParseData(self, request: Request, game_table: GameTable):
        db_cursor = self._db.cursor()
        data_directory = self._settings["DATA_DIR"] + self._game_id
        db_settings = self._settings["db_config"]
        
        # logging.debug("complex_data_index: {}".format(complex_data_index))

        # First, get the files and game-specific vars ready
        game_schema: Schema
        game_extractor: type
        if self._game_id == "WAVES":
            game_schema = Schema(schema_name="WAVES.json")
            game_extractor = WaveExtractor
        elif self._game_id == "CRYSTAL":
            game_schema = Schema(schema_name="CRYSTAL.json")
            game_extractor = CrystalExtractor
        elif self._game_id == "LAKELAND":
            game_schema = Schema(schema_name="LAKELAND.json")
            game_extractor = LakelandExtractor
        else:
            raise Exception("Got an invalid game ID!")

        dataset_id = "{}_{}_to_{}".format(self._game_id, request.start_date.strftime("%Y%m%d"),\
                                        request.end_date.strftime("%Y%m%d"))
        raw_csv_name = f"{dataset_id}_raw.csv"
        raw_csv_full_path = f"{data_directory}/{raw_csv_name}"
        proc_csv_name  = f"{dataset_id}_proc.csv"
        proc_csv_full_path = f"{data_directory}/{proc_csv_name}"
        os.makedirs(name=data_directory, exist_ok=True)
        raw_csv_file = open(raw_csv_full_path, "w")
        proc_csv_file = open(proc_csv_full_path, "w")

        # Now, we're ready to set up the managers:
        raw_mgr = RawManager(game_table=game_table, game_schema=game_schema, raw_csv_file=raw_csv_file)
        proc_mgr = ProcManager(ExtractorClass=game_extractor, game_table=game_table, game_schema=game_schema, proc_csv_file=proc_csv_file )
        
        # We're moving the metadata out into a separate readme file.
        # # Next, calculate metadata
        # raw_metadata = utils.csvMetadata(game_name=self._game_id, begin_date=request.start_date, end_date=request.end_date,
        #                                 field_list=game_schema.db_columns_with_types())
        # feature_descriptions = {**game_schema.perlevel_features(), **game_schema.aggregate_features()}
        # proc_metadata = utils.csvMetadata(game_name=self._game_id, begin_date=request.start_date, end_date=request.end_date,
        #                                 field_list=feature_descriptions)
        # # after generating the metadata, write to each file
        # raw_csv_file.write(raw_metadata)
        # proc_csv_file.write(proc_metadata)

        # then write the column headers for the raw csv.
        raw_mgr.WriteRawCSVHeader()
        proc_mgr.WriteProcCSVHeader()

        num_sess = len(game_table.session_ids)
        slice_size = self._settings["BATCH_SIZE"]
        session_slices = [[game_table.session_ids[i] for i in
                        range( j*slice_size, min((j+1)*slice_size - 1, num_sess) )] for j in
                        range( 0, math.ceil(num_sess / slice_size) )]
        for next_slice in session_slices:
            # grab data for the given session range. Sort by event time, so 
            # TODO: Take the "WAVES" out of the line of code below.
            filt = f"app_id='{self._game_id}' AND (session_id  BETWEEN '{next_slice[0]}' AND '{next_slice[-1]}')"
            next_data_set = utils.SQL.SELECT(cursor=db_cursor, db_name=db_settings["DB_NAME_DATA"], table=db_settings["table"],
                                            filter=filt, sort_columns=["session_id", "session_n"], sort_direction = "ASC",
                                            distinct=False)
            # now, we process each row.
            start = datetime.now()
            for row in next_data_set:
                self._processRow(row, game_table, raw_mgr, proc_mgr)
            time_delta = datetime.now() - start
            logging.info("Slice processing time: {} min, {:.3f} sec".format(
                math.floor(time_delta.total_seconds()/60), time_delta.total_seconds() % 60)
            )
            
            # after processing all rows for all slices, write out the session data and reset for next slice.
            raw_mgr.WriteRawCSVLines()
            raw_mgr.ClearLines()
            proc_mgr.calculateAggregateFeatures()
            proc_mgr.WriteProcCSVLines()
            proc_mgr.ClearLines()

        # Finally, update the list of csv files.
        self._updateFileExportList(dataset_id, raw_csv_full_path, proc_csv_full_path,
                                   request, num_sess)

        return True

    ## Private helper function to process a single row of data.
    #  Most of the processing is delegated to Raw and Proc Managers, but this
    #  function does a bit of pre-processing to parse the event_data_custom.
    #  @param row        The raw row data from a SQL query result.
    #  @param game_table A data structure containing information on how the db
    #                    table assiciated with the given game is structured. 
    #  @raw_mgr          An instance of RawManager used to track raw data.
    #  @proc_mgr         An instance of ProcManager used to extract and track feature data.
    def _processRow(self, row: typing.Tuple, game_table: GameTable, raw_mgr: RawManager, proc_mgr: ProcManager):
        session_id = row[game_table.session_id_index]

        # parse out complex data from json
        col = row[game_table.complex_data_index]
        complex_data_parsed = json.loads(col) if (col is not None) else {"event_custom":row[game_table.event_index]}
        # make sure we get *something* in the event_custom name
        # TODO: Make a better solution for games without event_custom fields in the logs themselves
        if self._game_id == 'LAKELAND' or self._game_id == 'JOWILDER':
            complex_data_parsed["event_custom"] = row[game_table.event_custom_index]
        elif "event_custom" not in complex_data_parsed.keys():
            complex_data_parsed["event_custom"] = row[game_table.event_index]
        # replace the json with parsed version.
        row = list(row)
        row[game_table.complex_data_index] = complex_data_parsed

        if session_id in game_table.session_ids:
            raw_mgr.ProcessRow(row)
            proc_mgr.ProcessRow(row)
        # else:
            # in this case, we should have just found 
            # logging.warn(f"Found a session ({session_id}) which was in the slice but not in the list of sessions for processing.")

    ## Private helper function to update the list of exported files.
    #  Given the paths of the exported files, and some other variables for
    #  deriving file metadata, this simply updates the JSON file to the latest
    #  list of files.
    #  @param dataset_id    The id used to identify a specific data set, based on
    #                       game id, and range of dates.
    #  @param raw_csv_path  Path to the newly exported raw csv, including filename
    #  @param proc_csv_path Path to the newly exported feature csv, including filename
    #  @param request       The original request for data export
    #  @param num_sess      The number of sessions included in the recent export.
    def _updateFileExportList(self, dataset_id: str, raw_csv_path: str, proc_csv_path: str,
        request: Request, num_sess: int):
        existing_csvs = utils.loadJSONFile("file_list.json", self._settings["DATA_DIR"]) or {}

        existing_csv_file = open("{}/file_list.json".format(self._settings["DATA_DIR"]), "w")
        if not self._game_id in existing_csvs:
            existing_csvs[self._game_id] = {}
        # raw_stat = os.stat(raw_csv_full_path)
        # proc_stat = os.stat(proc_csv_full_path)
        existing_csvs[self._game_id][dataset_id] = \
            {"raw":raw_csv_path,
            "proc":proc_csv_path,
            "start_date":request.start_date.strftime("%m-%d-%Y"),
            "end_date":request.end_date.strftime("%m-%d-%Y"),
            "date_modified":datetime.now().strftime("%m-%d-%Y"),
            "sessions":num_sess
            }
        existing_csv_file.write(json.dumps(existing_csvs, indent=4))