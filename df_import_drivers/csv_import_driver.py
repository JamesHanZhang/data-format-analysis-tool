"""
*****************************************
***        DATA-ANALYSIS-PROJECT      ***
***         AUTHOR: JamesHanZhang     ***
***        jameshanzhang@foxmail.com  ***
*****************************************
"""

import pandas as pd
import re
import csv
import shlex
import os
# self-made modules
from df_import_drivers.df_import_driver import DfImportDriver
from across_process import SysLog

class CsvImportDriver(DfImportDriver):
    def __init__(self):
        super().__init__()
        self.input_encoding = self.table_properties['basic_params']['input_encoding']
        self.input_sep = self.table_properties['params']['input_sep']
        self.quote_none = self.table_properties['basic_params']['quote_none']
        self.chunksize = self.table_properties['basic_params']['chunksize']

    def decide_quote_none(self):
        if self.quote_none is True:
            # 忽视引号作为分隔符，以保证数据完整性
            quoting = csv.QUOTE_NONE
        else:
            # 不忽视引号作为分隔符，是默认值
            quoting = csv.QUOTE_MINIMAL
        return quoting

    def read_columns_from_csv(self, input_path):
        """
        return the columns in csv file.
        """
        with open(input_path, mode='r', encoding=self.input_encoding) as file:
            columns = file.readline()
            columns = columns[:-1]
            columns = columns.split(self.input_sep)
            new_columns = list()
            for each_col in columns:
                new_col = each_col.strip("\"")
                new_col = new_col.strip(" ")
                new_columns.append(new_col)
        return new_columns

    def get_preserves(self, full_input_path):
        """method for getting dict of CSV columns and return it with 'object' type as indicator."""
        new_columns = self.read_columns_from_csv(full_input_path)
        objects = ['object'] * len(new_columns)
        preserves = dict(zip(new_columns, objects))
        return preserves

    def decide_df_dtypes(self, full_input_path) -> dict[str, str]|None:
        preserves = self.get_preserves(full_input_path)
        preserves = self.get_df_dtypes_by_preserves(preserves)
        return preserves

    def split_line_with_quotes(self, line, sep):
        # 去掉换行符
        line = line.strip("\n")
        # 基于双引号作为分隔符补充的拆分
        space_replacement = "$a@c$%sa&"
        quote_replacement = "#@!&dxa&0saw2=&"
        null_replacement = "$*(3$1!$^_@@"
        # 把中间的双引号替换掉
        while True:
            if re.search(r'([^{a}]+)\"+([^{a}]+)'.format(a=sep), line) is not None:
                line = re.sub(r'([^{a}]+)\"([^{a}]+)'.format(a=sep), r'\1{a}\2'.format(a=quote_replacement), line)
            else:
                break
        if line.count("\"") % 2 != 0:
            # 说明有贴单边的双引号，容易引起歧义，需要反馈问题
            # 这种情况下导入为dataframe同样会引发歧义，所以需要存入error_lines的表内做二次处理
            return None

        # 将不带双引号的空选项转为null_replacement，否则shlex.split会把空格直接忽略，以至于跳过空值
        line = sep + line + sep
        new_line = str()
        for i in range(len(line) - 1):
            if line[i] == line[i + 1] and line[i] == sep:
                new_line += line[i] + null_replacement
            else:
                new_line += line[i]
        line = new_line[1:]

        # 将空格替换为复杂字符串，将分隔符替换为空格 - 方便使用shlex
        line = line.replace(' ', space_replacement)
        line = line.replace(sep, ' ')

        elem_list = shlex.split(line)
        res_list = list()
        for elem in elem_list:
            take_sep_back = elem.replace(' ', sep)
            take_space_back = take_sep_back.replace(space_replacement, ' ')
            take_quote_back = take_space_back.replace(quote_replacement, '\"')
            # 将空值换为None
            if take_quote_back == "" or take_quote_back == null_replacement:
                res_list.append(None)
                continue
            res_list.append(take_quote_back)
        return res_list

    def split_line(self, line):
        # quote_none 表示是否将双引号视为内容而非分隔符的补充，True表示视为内容，False表示为分隔符的补充
        if self.quote_none is False:
            field_list = self.split_line_with_quotes(line, self.input_sep)
            return field_list

        field_list = line.split(self.input_sep)
        return field_list

    def direct_raise_parse_error(self, pos: int):
        msg = "[ParseError]: ParseError detected not by read_csv, but by self made method.\n" \
              "Error tokenizing data. C error: EOF inside string starting at row {b}.\n".format(b=str(pos))
        self.log.show_log(msg)
        raise pd.errors.ParserError(msg)

    def raise_parse_error(self, full_input_path):
        # 自主搭建的CSV常无法准确识别column和各行的列数，因此需要验证一下
        # 如果column有5个，而第一行有7个，那么只有第一行的后5个会被录入，且不会报错
        # 这种情况在read_csv中比较常见，因此为了避免这种情况，追求更精确的准确性，创建该函数进行报错
        columns = self.read_columns_from_csv(full_input_path)
        col_num = len(columns)
        with open(full_input_path, mode='r+', encoding=self.input_encoding) as file:
            pos = 0
            while True:
                # 通过指针一条一条地读取
                line = file.readline()
                field_list = self.split_line(line)
                if field_list is None:
                    self.direct_raise_parse_error(pos)
                if len(field_list) != col_num:
                    self.direct_raise_parse_error(pos)
                if not line:
                    break
                pos += 1
        return

    @SysLog().direct_show_log("[ERROR LINES EXTRACTION] error lines and correct lines are separated into 2 files for further reading.")
    def sep_out_error_lines(self, full_input_path, reason) -> str:
        """
        debug error e.g.
        pandas.errors.ParserError: Error tokenizing data. C error: Expected 66 fields in line 348, saw 68
        pandas.errors.ParserError: Error tokenizing data. C error: EOF inside string starting at row 39.
        出现问题的集中到error_csv
        没问题的集中到del_error_csv
        """
        # 将错误的行保存进导出目录下，以便统一处理
        columns = self.read_columns_from_csv(full_input_path)
        col_num = len(columns)
        input_path = os.path.dirname(full_input_path)
        input_file = self.iom.get_main_file_name(full_input_path)
        error_csv = "{a}_error_lines.csv".format(a=self.iom.join_path(input_path,input_file))
        del_error_csv = "{a}_originalcsv(error_deleted).csv".format(a=self.iom.join_path(input_path,input_file))

        with open(full_input_path, mode= 'r+', encoding = self.input_encoding) as file:
            first_line = file.readline()
            self.iom.store_file(error_csv, first_line, overwrite=True)
            # 保存不带脏数据的副本
            self.iom.store_file(del_error_csv, first_line, overwrite=True)

            part_error_lines = ""
            part_correct_lines = ""
            error_mark = False
            while True:
                # 直接进入下一条
                # 通过指针一条一条地读取，返回的行末尾自带一个换行符
                line = file.readline()
                # 最后空了就停止循环
                if not line:
                    print("\nthe process for storing csv file without error lines is finished.\n"
                          "and the process file was loaded into the processing and deleted already.\n")
                    break

                field_list = self.split_line(line)

                # 说明出现EOF错误问题，直接保存到error lines
                if field_list is None:
                    part_error_lines += line

                # 如果字段数不匹配，则保存到error lines
                else:
                    field_num = len(field_list)
                    if field_num != col_num:
                        part_error_lines += line

                    # 如果字段数匹配，且不是头一行，则保存到副本
                    if field_num == col_num:
                        part_correct_lines += line

                if len(part_error_lines) != 0:
                    error_mark = True

                if len(part_error_lines) > 5000000:
                    self.iom.store_file(error_csv, part_error_lines, overwrite=False)
                    part_error_lines = ""
                if len(part_correct_lines) > 5000000:
                    self.iom.store_file(del_error_csv, part_correct_lines, overwrite=False)
                    part_correct_lines = ""
            # 循环结束后的剩余的部分
            if len(part_error_lines) != 0:
                self.iom.store_file(error_csv, part_error_lines, overwrite=False)
            if len(part_correct_lines) != 0:
                self.iom.store_file(del_error_csv, part_correct_lines, overwrite=False)

        if error_mark is False:
            self.iom.remove_file(error_csv)
            self.iom.remove_file(del_error_csv)
            del_error_csv = full_input_path
        else:
            # 保存错误
            msg = "[ParserError]: {a} \n" \
                  "And the error lines weren't processed.\n" \
                  "Those error lines were stored as {b}.".format(
                a=str(reason), b=error_csv)
            self.log.show_log(msg)
        return del_error_csv

    def init_csv_reader_params(self, input_file: str, input_path= "", input_sep="", input_encoding="") -> str:
        if input_path != "":
            self.input_path = input_path
        if input_sep != "":
            self.input_sep = input_sep
        if input_encoding != "":
            self.input_encoding = input_encoding
        full_input_path = self.iom.join_path(self.input_path, input_file)
        self.iom.check_if_file_exists(full_input_path)

        # 通过quote_as_object判断，是否把所有类型转为object再次进行读取，以保证得到完整数据
        self.preserves = self.decide_df_dtypes(full_input_path)
        # 判断是否严格判断引号为分隔符的一部分(贴近分隔符的时候)，还是视为数据内容录入
        self.quoting = self.decide_quote_none()

        try:
            # 第一行必须为准确的列数，否则会默认识别为后半部分符合HEADER列数要求的部分数据，然后后面凡是没有的则包None，就错误了，所以这里引入更敏感的parser_error发觉方法
            self.raise_parse_error(full_input_path)
        except (pd.errors.ParserError) as reason:
            # 保存无错集到del_error_csv
            full_input_path = self.sep_out_error_lines(full_input_path, reason)

        return full_input_path


    @SysLog().calculate_cost_time("<import from csv>")
    def fully_import_csv(self, input_file: str, input_path="", input_sep="", input_encoding="") -> pd.DataFrame:
        full_input_path = self.init_csv_reader_params(input_file, input_path, input_sep, input_encoding)
        df = pd.read_csv(full_input_path, sep=self.input_sep, encoding=self.input_encoding, dtype=self.preserves,
                         quoting=self.quoting, on_bad_lines='warn')
        msg = "[IMPORT CSV]: data from {a} is fully imported.".format(a=full_input_path)
        self.log.show_log(msg)
        return df

    @SysLog().calculate_cost_time("<csv reading generator created>")
    def circular_import_csv(self, input_file: str, input_path="", input_sep="", input_encoding=""):
        full_input_path = self.init_csv_reader_params(input_file, input_path, input_sep, input_encoding)
        # generate the generator of csv reading method for importing big csv
        chunk_reader = pd.read_csv(full_input_path, sep=self.input_sep, encoding=self.input_encoding,
                                   chunksize=self.chunksize, dtype=self.preserves, quoting=self.quoting,
                                   on_bad_lines='warn')
        msg = "[IMPORT CSV]: data from {a} is imported as reader generator for circular import in chunk size.".format(a=full_input_path)
        self.log.show_log(msg)
        return chunk_reader