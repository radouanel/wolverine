
import string
import datetime
from pathlib import Path

import xlsxwriter

from wolverine import utils


HEADER_LIST = ['Shot', 'Preview', 'IN', 'OUT', 'Duration', 'Brief', 'Work', 'Feedback']
DEFAULT_LOGO = Path(__file__).parents[1].joinpath('resources/icons/brunch_b.png')
DEFAULT_LOGO_SCALE = [2.55, 2.8]


def create_fill_xml(output_path, source_file, fps, shots_list):
    print("creating excel file")

    output_path = Path(output_path)
    # Create a new Excel file and add a worksheet.
    workbook = xlsxwriter.Workbook(output_path.as_posix())
    worksheet = workbook.add_worksheet()

    workbook, xlsx_styles = create_xlsx_style(workbook)
    worksheet = fill_logo(worksheet)

    fill_xlsx_description(source_file, worksheet, xlsx_styles)
    fill_xlsx_data(shots_list, fps, worksheet, xlsx_styles)
    stylise_xlsx(worksheet)
    try:
        workbook.close()
    except Exception as e:
        print(e)
        return False
    return True


def fill_logo(worksheet, logo_path='', logo_height=174, logo_scale=None):
    logo_scale_x, logo_scale_y = logo_scale or DEFAULT_LOGO_SCALE
    logo_path = Path(logo_path or DEFAULT_LOGO)
    worksheet.insert_image("B1", logo_path, {'x_scale': logo_scale_x, 'y_scale': logo_scale_y})
    worksheet.set_row(0, logo_height)
    return worksheet


def create_xlsx_style(workbook):
    xlsx_styles = {
        "bold": workbook.add_format({'bold': True}),
        "italic": workbook.add_format({'italic': True}),
        "grey_bold": workbook.add_format({'font_name': 'Arial', 'font_size': 16, 'bold': True, 'border': 1,
                                          'bg_color': '#D8D8D8', 'valign': 'vcenter', 'align': 'center'}),
        "image": workbook.add_format({'border': 1, 'valign': 'vcenter', 'align': 'center'}),
        "basic": workbook.add_format({'font_name': 'Arial', 'font_size': 16, 'border': 1, 'valign': 'vcenter',
                                      'align': 'center'}),
        "basic_borderless": workbook.add_format({'font_name': 'Arial', 'font_size': 16, 'valign': 'vcenter',
                                                 'align': 'center'}),
        "big_arial": workbook.add_format({'font_name': 'Arial', 'font_size': 20, 'valign': 'bottom', 'align': 'right'}),
        "big_bold_arial": workbook.add_format({'font_name': 'Arial', 'font_size': 48, 'bold': True, 'valign': 'top',
                                               'align': 'right'}),
        "big_italic_arial": workbook.add_format({'font_name': 'Arial', 'font_size': 20, 'italic': True,
                                                 'valign': 'bottom', 'align': 'left'}),
    }
    return workbook, xlsx_styles


def fill_xlsx_description(source_path, worksheet, xlsx_styles):
    source_path = Path(source_path)
    description_data = {
        "PROJECT": '',
        "Source": source_path.stem,
        "Date": datetime.datetime.today().strftime("%d-%m-%Y"),
        "Agency": '',
        "Production": '',
        "Director": '',
        "Producer": '',
        "Post-Producer": ''
    }
    worksheet.write("I1", "SHOT LIST", xlsx_styles.get("big_bold_arial"))

    start_row = 4
    columns_desc = [2, 3]
    columns = string.ascii_uppercase[:26]
    for c in columns_desc:
        worksheet.set_row(c, 22.5)
        for row, desc, desc_value in enumerate(description_data.items()):
            row += start_row
            worksheet.set_row(row, 22.5)
            cur_column = f'{columns[c]}{row}'
            if c == columns_desc[0]:
                desc += ' :' if row != 0 else ''
                worksheet.write(cur_column, str(desc), xlsx_styles.get("big_arial"))
            else:
                worksheet.write(cur_column, str(desc_value), xlsx_styles.get("big_italic_arial"))


def fill_xlsx_data(shots_list, fps, worksheet, xlsx_styles):
    start_row = 14
    merge_columns = ["B", "C", "G", "H", "I"]
    double_cell_columns = ["IN", "OUT", "Duration"]
    columns = string.ascii_uppercase[:26]

    added_headers = False
    add1 = add2 = 0
    for i, shot_data in enumerate(shots_list):
        cur_row = i + start_row
        cur_row1, cur_row2, add1, add2 = get_row_id(i == 0, cur_row, add1, add2)
        worksheet.set_row(cur_row1, 21)
        worksheet.set_row(cur_row2, 81)
        for clm in merge_columns:
            worksheet.merge_range(f'{clm}{cur_row2}:{clm}{cur_row1}', "", xlsx_styles["basic"])
        for header_index, header in enumerate(HEADER_LIST):
            header_index += 1
            shot_header = shot_data.get(header)
            #headers
            if not added_headers and header not in ['Shot', 'Preview']:
                cur_column = columns[header_index] + str(13)
                worksheet.write(cur_column, header, xlsx_styles["grey_bold"])
            # row1
            cur_column = columns[header_index] + str(cur_row1)
            if header in double_cell_columns:
                cur_timecode = utils.calculate_time_code(fps, shot_header)
                cur_text = f'{int(cur_timecode[-1]):04d}'
                worksheet.write(cur_column, cur_text, xlsx_styles["basic"])
            # row2
            cur_column = columns[header_index] + str(cur_row2)
            cur_text = str(shot_header)
            if header in double_cell_columns:
                cur_timecode = utils.calculate_time_code(fps, shot_header)
                cur_text = str(':'.join([f'{f:02d}' for f in cur_timecode[:-1]]))
            if columns[header_index] == "C" and shot_data.thumbail and shot_data.thumbail.exists():
                worksheet.write(cur_column, "", xlsx_styles["image"])
                worksheet.insert_image(cur_column, shot_data.thumbail.as_posix(), {'x_scale': 1.03, 'y_scale': 1.8})
            else:
                if header == "Shot":
                    cur_text = f'PL{shot_data.index:03d}'
                worksheet.write(cur_column, cur_text, xlsx_styles["basic"])
        added_headers = True

    return worksheet


def get_row_id(first_run, row, add1, add2):
    row1 = row2 = row
    if first_run:
        if row % 2 != 0:
            add2 += 1
        else:
            add1 += 1
    else:
        add1 += 1
        add2 += 1
    row1 += add1
    row2 += add2
    return row1, row2, add1, add2


def stylise_xlsx(worksheet):
    column_params = {"A": 0.75, "B": 9.25, "C": 19.25, "D": 16.5, "E": 16.5,
                     "F": 16.5, "G": 54.5, "H": 54.5, "I": 54.5}
    for column_id, column_size in column_params.items():
        worksheet.set_column(f'{column_id}:{column_size}')
    worksheet.set_row(11, 51.75)
    worksheet.set_row(12, 33.75)

    return worksheet

