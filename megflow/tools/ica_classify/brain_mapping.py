# coding:utf-8
# 映射不同脑磁设备下，不同脑区对应的通道。
import mne
from mne.channels.channels import _divide_to_regions

# User Define
BRAIN_MAPPING = {
    "neuromag":
        {
            'Left-frontal': ['MEG0121', 'MEG0122', 'MEG0123', 'MEG0311', 'MEG0312', 'MEG0313', 'MEG0321', 'MEG0322',
                             'MEG0323', 'MEG0331', 'MEG0332', 'MEG0333', 'MEG0341', 'MEG0342', 'MEG0343', 'MEG0511',
                             'MEG0512', 'MEG0513', 'MEG0521', 'MEG0522', 'MEG0523', 'MEG0531', 'MEG0532', 'MEG0533',
                             'MEG0541', 'MEG0542', 'MEG0543', 'MEG0611', 'MEG0612', 'MEG0613', 'MEG0621', 'MEG0622',
                             'MEG0623', 'MEG0641', 'MEG0642', 'MEG0643', 'MEG0821', 'MEG0822', 'MEG0823'],
            'Right-frontal': ['MEG0811', 'MEG0812', 'MEG0813', 'MEG0911', 'MEG0912', 'MEG0913', 'MEG0921', 'MEG0922',
                              'MEG0923', 'MEG0931', 'MEG0932', 'MEG0933', 'MEG0941', 'MEG0942', 'MEG0943', 'MEG1011',
                              'MEG1012', 'MEG1013', 'MEG1021', 'MEG1022', 'MEG1023', 'MEG1031', 'MEG1032', 'MEG1033',
                              'MEG1211', 'MEG1212', 'MEG1213', 'MEG1221', 'MEG1222', 'MEG1223', 'MEG1231', 'MEG1232',
                              'MEG1233', 'MEG1241', 'MEG1242', 'MEG1243', 'MEG1411', 'MEG1412', 'MEG1413'],
            'Left-temporal': ['MEG0111', 'MEG0112', 'MEG0113', 'MEG0131', 'MEG0132', 'MEG0133', 'MEG0141', 'MEG0142',
                              'MEG0143', 'MEG0211', 'MEG0212', 'MEG0213', 'MEG0221', 'MEG0222', 'MEG0223', 'MEG0231',
                              'MEG0232', 'MEG0233', 'MEG0241', 'MEG0242', 'MEG0243', 'MEG1511', 'MEG1512', 'MEG1513',
                              'MEG1521', 'MEG1522', 'MEG1523', 'MEG1531', 'MEG1532', 'MEG1533', 'MEG1541', 'MEG1542',
                              'MEG1543', 'MEG1611', 'MEG1612', 'MEG1613', 'MEG1621', 'MEG1622', 'MEG1623'],
            'Right-temporal': ['MEG1311', 'MEG1312', 'MEG1313', 'MEG1321', 'MEG1322', 'MEG1323', 'MEG1331', 'MEG1332',
                               'MEG1333', 'MEG1341', 'MEG1342', 'MEG1343', 'MEG1421', 'MEG1422', 'MEG1423', 'MEG1431',
                               'MEG1432', 'MEG1433', 'MEG1441', 'MEG1442', 'MEG1443', 'MEG2411', 'MEG2412', 'MEG2413',
                               'MEG2421', 'MEG2422', 'MEG2423', 'MEG2611', 'MEG2612', 'MEG2613', 'MEG2621', 'MEG2622',
                               'MEG2623', 'MEG2631', 'MEG2632', 'MEG2633', 'MEG2641', 'MEG2642', 'MEG2643'],
            'Left-occipital': ['MEG1641', 'MEG1642', 'MEG1643', 'MEG1711', 'MEG1712', 'MEG1713', 'MEG1721', 'MEG1722',
                               'MEG1723', 'MEG1731', 'MEG1732', 'MEG1733', 'MEG1741', 'MEG1742', 'MEG1743', 'MEG1911',
                               'MEG1912', 'MEG1913', 'MEG1921', 'MEG1922', 'MEG1923', 'MEG1931', 'MEG1932', 'MEG1933',
                               'MEG1941', 'MEG1942', 'MEG1943', 'MEG2041', 'MEG2042', 'MEG2043', 'MEG2111', 'MEG2112',
                               'MEG2113', 'MEG2141', 'MEG2142', 'MEG2143'],
            'Right-occipital': ['MEG2031', 'MEG2032', 'MEG2033', 'MEG2121', 'MEG2122', 'MEG2123', 'MEG2131', 'MEG2132',
                                'MEG2133', 'MEG2311', 'MEG2312', 'MEG2313', 'MEG2321', 'MEG2322', 'MEG2323', 'MEG2331',
                                'MEG2332', 'MEG2333', 'MEG2341', 'MEG2342', 'MEG2343', 'MEG2431', 'MEG2432', 'MEG2433',
                                'MEG2511', 'MEG2512', 'MEG2513', 'MEG2521', 'MEG2522', 'MEG2523', 'MEG2531', 'MEG2532',
                                'MEG2533', 'MEG2541', 'MEG2542', 'MEG2543']
        },
    # all CTF MEG channels start with "M"
    # all CTF reference channels start with B, G, P, Q or R
    # all CTF EEG channels start with "EEG"
    # 'MZ': for MEG zenith
    # 'ML': for MEG left
    # 'MR': for MEG right
    # 'MLx', 'MRx' and 'MZx' with x=C,F,O,P,T for left/right central, frontal, occipital, parietal and temporal
    #  ref from ft_channelselection()
    #  ref from https://github.com/hoechenberger/mne-python/blob/main/mne/channels/data/layouts/CTF-275.lout
    "ctf":
        {
            'Left-frontal': ['MLF11-4408', 'MLF12-4408', 'MLF13-4408', 'MLF14-4408', 'MLF21-4408', 'MLF22-4408', 'MLF23-4408', 'MLF24-4408', 'MLF25-4408', 'MLF31-4408', 'MLF32-4408', 'MLF33-4408', 'MLF34-4408', 'MLF35-4408', 'MLF41-4408', 'MLF42-4408', 'MLF43-4408', 'MLF44-4408', 'MLF45-4408', 'MLF46-4408', 'MLF51-4408', 'MLF52-4408', 'MLF53-4408', 'MLF54-4408', 'MLF55-4408', 'MLF56-4408', 'MLF61-4408', 'MLF62-4408', 'MLF63-4408', 'MLF64-4408', 'MLF65-4408', 'MLF66-4408', 'MLF67-4408'],
            'Right-frontal': [ 'MRF11-4408', 'MRF12-4408', 'MRF13-4408', 'MRF14-4408', 'MRF21-4408', 'MRF22-4408', 'MRF23-4408', 'MRF24-4408', 'MRF25-4408', 'MRF31-4408', 'MRF32-4408', 'MRF33-4408', 'MRF34-4408', 'MRF35-4408', 'MRF41-4408', 'MRF42-4408', 'MRF43-4408', 'MRF44-4408', 'MRF45-4408', 'MRF46-4408', 'MRF51-4408', 'MRF52-4408', 'MRF53-4408', 'MRF54-4408', 'MRF55-4408', 'MRF56-4408', 'MRF61-4408', 'MRF62-4408', 'MRF63-4408', 'MRF64-4408', 'MRF65-4408', 'MRF66-4408', 'MRF67-4408'],
            'Left-temporal': ['MLT11-4408', 'MLT12-4408', 'MLT13-4408', 'MLT14-4408', 'MLT15-4408', 'MLT16-4408', 'MLT21-4408', 'MLT22-4408', 'MLT23-4408', 'MLT24-4408', 'MLT25-4408', 'MLT26-4408', 'MLT27-4408', 'MLT31-4408', 'MLT32-4408', 'MLT33-4408', 'MLT34-4408', 'MLT35-4408', 'MLT36-4408', 'MLT37-4408', 'MLT41-4408', 'MLT42-4408', 'MLT43-4408', 'MLT44-4408', 'MLT45-4408', 'MLT46-4408', 'MLT47-4408', 'MLT51-4408', 'MLT52-4408', 'MLT53-4408', 'MLT54-4408', 'MLT55-4408', 'MLT56-4408', 'MLT57-4408'],
            'Right-temporal': ['MRT11-4408', 'MRT12-4408', 'MRT13-4408', 'MRT14-4408', 'MRT15-4408', 'MRT16-4408', 'MRT21-4408', 'MRT22-4408', 'MRT23-4408', 'MRT24-4408', 'MRT25-4408', 'MRT26-4408', 'MRT31-4408', 'MRT32-4408', 'MRT33-4408', 'MRT34-4408', 'MRT35-4408', 'MRT36-4408', 'MRT37-4408', 'MRT41-4408', 'MRT42-4408', 'MRT43-4408', 'MRT44-4408', 'MRT45-4408', 'MRT46-4408', 'MRT51-4408', 'MRT52-4408', 'MRT53-4408', 'MRT54-4408', 'MRT55-4408', 'MRT56-4408'],
            'Right-occipital': [ 'MRO11-4408', 'MRO12-4408', 'MRO13-4408', 'MRO14-4408', 'MRO21-4408', 'MRO22-4408', 'MRO23-4408', 'MRO24-4408', 'MRO31-4408', 'MRO32-4408', 'MRO33-4408', 'MRO34-4408', 'MRO41-4408', 'MRO42-4408', 'MRO43-4408', 'MRO44-4408', 'MRO51-4408', 'MRO52-4408', 'MRO53-4408'],
            'Left-occipital': ['MLO11-4408', 'MLO12-4408', 'MLO13-4408', 'MLO14-4408', 'MLO21-4408', 'MLO22-4408', 'MLO23-4408', 'MLO24-4408', 'MLO31-4408', 'MLO32-4408', 'MLO33-4408', 'MLO34-4408', 'MLO41-4408', 'MLO42-4408', 'MLO43-4408', 'MLO44-4408', 'MLO51-4408', 'MLO52-4408', 'MLO53-4408']
        },
}

CHAN_MAPPING = {
    "neuromag": {'MEG0111': 0, 'MEG0112': 1, 'MEG0113': 2, 'MEG0121': 3, 'MEG0122': 4, 'MEG0123': 5, 'MEG0131': 6,
                 'MEG0132': 7, 'MEG0133': 8, 'MEG0141': 9, 'MEG0142': 10, 'MEG0143': 11, 'MEG0211': 12, 'MEG0212': 13,
                 'MEG0213': 14, 'MEG0221': 15, 'MEG0222': 16, 'MEG0223': 17, 'MEG0231': 18, 'MEG0232': 19,
                 'MEG0233': 20, 'MEG0241': 21, 'MEG0242': 22, 'MEG0243': 23, 'MEG0311': 24, 'MEG0312': 25,
                 'MEG0313': 26, 'MEG0321': 27, 'MEG0322': 28, 'MEG0323': 29, 'MEG0331': 30, 'MEG0332': 31,
                 'MEG0333': 32, 'MEG0341': 33, 'MEG0342': 34, 'MEG0343': 35, 'MEG0411': 36, 'MEG0412': 37,
                 'MEG0413': 38, 'MEG0421': 39, 'MEG0422': 40, 'MEG0423': 41, 'MEG0431': 42, 'MEG0432': 43,
                 'MEG0433': 44, 'MEG0441': 45, 'MEG0442': 46, 'MEG0443': 47, 'MEG0511': 48, 'MEG0512': 49,
                 'MEG0513': 50, 'MEG0521': 51, 'MEG0522': 52, 'MEG0523': 53, 'MEG0531': 54, 'MEG0532': 55,
                 'MEG0533': 56, 'MEG0541': 57, 'MEG0542': 58, 'MEG0543': 59, 'MEG0611': 60, 'MEG0612': 61,
                 'MEG0613': 62, 'MEG0621': 63, 'MEG0622': 64, 'MEG0623': 65, 'MEG0631': 66, 'MEG0632': 67,
                 'MEG0633': 68, 'MEG0641': 69, 'MEG0642': 70, 'MEG0643': 71, 'MEG0711': 72, 'MEG0712': 73,
                 'MEG0713': 74, 'MEG0721': 75, 'MEG0722': 76, 'MEG0723': 77, 'MEG0731': 78, 'MEG0732': 79,
                 'MEG0733': 80, 'MEG0741': 81, 'MEG0742': 82, 'MEG0743': 83, 'MEG0811': 84, 'MEG0812': 85,
                 'MEG0813': 86, 'MEG0821': 87, 'MEG0822': 88, 'MEG0823': 89, 'MEG0911': 90, 'MEG0912': 91,
                 'MEG0913': 92, 'MEG0921': 93, 'MEG0922': 94, 'MEG0923': 95, 'MEG0931': 96, 'MEG0932': 97,
                 'MEG0933': 98, 'MEG0941': 99, 'MEG0942': 100, 'MEG0943': 101, 'MEG1011': 102, 'MEG1012': 103,
                 'MEG1013': 104, 'MEG1021': 105, 'MEG1022': 106, 'MEG1023': 107, 'MEG1031': 108, 'MEG1032': 109,
                 'MEG1033': 110, 'MEG1041': 111, 'MEG1042': 112, 'MEG1043': 113, 'MEG1111': 114, 'MEG1112': 115,
                 'MEG1113': 116, 'MEG1121': 117, 'MEG1122': 118, 'MEG1123': 119, 'MEG1131': 120, 'MEG1132': 121,
                 'MEG1133': 122, 'MEG1141': 123, 'MEG1142': 124, 'MEG1143': 125, 'MEG1211': 126, 'MEG1212': 127,
                 'MEG1213': 128, 'MEG1221': 129, 'MEG1222': 130, 'MEG1223': 131, 'MEG1231': 132, 'MEG1232': 133,
                 'MEG1233': 134, 'MEG1241': 135, 'MEG1242': 136, 'MEG1243': 137, 'MEG1311': 138, 'MEG1312': 139,
                 'MEG1313': 140, 'MEG1321': 141, 'MEG1322': 142, 'MEG1323': 143, 'MEG1331': 144, 'MEG1332': 145,
                 'MEG1333': 146, 'MEG1341': 147, 'MEG1342': 148, 'MEG1343': 149, 'MEG1411': 150, 'MEG1412': 151,
                 'MEG1413': 152, 'MEG1421': 153, 'MEG1422': 154, 'MEG1423': 155, 'MEG1431': 156, 'MEG1432': 157,
                 'MEG1433': 158, 'MEG1441': 159, 'MEG1442': 160, 'MEG1443': 161, 'MEG1511': 162, 'MEG1512': 163,
                 'MEG1513': 164, 'MEG1521': 165, 'MEG1522': 166, 'MEG1523': 167, 'MEG1531': 168, 'MEG1532': 169,
                 'MEG1533': 170, 'MEG1541': 171, 'MEG1542': 172, 'MEG1543': 173, 'MEG1611': 174, 'MEG1612': 175,
                 'MEG1613': 176, 'MEG1621': 177, 'MEG1622': 178, 'MEG1623': 179, 'MEG1631': 180, 'MEG1632': 181,
                 'MEG1633': 182, 'MEG1641': 183, 'MEG1642': 184, 'MEG1643': 185, 'MEG1711': 186, 'MEG1712': 187,
                 'MEG1713': 188, 'MEG1721': 189, 'MEG1722': 190, 'MEG1723': 191, 'MEG1731': 192, 'MEG1732': 193,
                 'MEG1733': 194, 'MEG1741': 195, 'MEG1742': 196, 'MEG1743': 197, 'MEG1811': 198, 'MEG1812': 199,
                 'MEG1813': 200, 'MEG1821': 201, 'MEG1822': 202, 'MEG1823': 203, 'MEG1831': 204, 'MEG1832': 205,
                 'MEG1833': 206, 'MEG1841': 207, 'MEG1842': 208, 'MEG1843': 209, 'MEG1911': 210, 'MEG1912': 211,
                 'MEG1913': 212, 'MEG1921': 213, 'MEG1922': 214, 'MEG1923': 215, 'MEG1931': 216, 'MEG1932': 217,
                 'MEG1933': 218, 'MEG1941': 219, 'MEG1942': 220, 'MEG1943': 221, 'MEG2011': 222, 'MEG2012': 223,
                 'MEG2013': 224, 'MEG2021': 225, 'MEG2022': 226, 'MEG2023': 227, 'MEG2031': 228, 'MEG2032': 229,
                 'MEG2033': 230, 'MEG2041': 231, 'MEG2042': 232, 'MEG2043': 233, 'MEG2111': 234, 'MEG2112': 235,
                 'MEG2113': 236, 'MEG2121': 237, 'MEG2122': 238, 'MEG2123': 239, 'MEG2131': 240, 'MEG2132': 241,
                 'MEG2133': 242, 'MEG2141': 243, 'MEG2142': 244, 'MEG2143': 245, 'MEG2211': 246, 'MEG2212': 247,
                 'MEG2213': 248, 'MEG2221': 249, 'MEG2222': 250, 'MEG2223': 251, 'MEG2231': 252, 'MEG2232': 253,
                 'MEG2233': 254, 'MEG2241': 255, 'MEG2242': 256, 'MEG2243': 257, 'MEG2311': 258, 'MEG2312': 259,
                 'MEG2313': 260, 'MEG2321': 261, 'MEG2322': 262, 'MEG2323': 263, 'MEG2331': 264, 'MEG2332': 265,
                 'MEG2333': 266, 'MEG2341': 267, 'MEG2342': 268, 'MEG2343': 269, 'MEG2411': 270, 'MEG2412': 271,
                 'MEG2413': 272, 'MEG2421': 273, 'MEG2422': 274, 'MEG2423': 275, 'MEG2431': 276, 'MEG2432': 277,
                 'MEG2433': 278, 'MEG2441': 279, 'MEG2442': 280, 'MEG2443': 281, 'MEG2511': 282, 'MEG2512': 283,
                 'MEG2513': 284, 'MEG2521': 285, 'MEG2522': 286, 'MEG2523': 287, 'MEG2531': 288, 'MEG2532': 289,
                 'MEG2533': 290, 'MEG2541': 291, 'MEG2542': 292, 'MEG2543': 293, 'MEG2611': 294, 'MEG2612': 295,
                 'MEG2613': 296, 'MEG2621': 297, 'MEG2622': 298, 'MEG2623': 299, 'MEG2631': 300, 'MEG2632': 301,
                 'MEG2633': 302, 'MEG2641': 303, 'MEG2642': 304, 'MEG2643': 305},

    "ctf": {'MLC11-4408': 0, 'MLC12-4408': 1, 'MLC13-4408': 2, 'MLC14-4408': 3, 'MLC15-4408': 4, 'MLC16-4408': 5,
            'MLC17-4408': 6, 'MLC21-4408': 7, 'MLC22-4408': 8, 'MLC23-4408': 9, 'MLC24-4408': 10, 'MLC25-4408': 11,
            'MLC31-4408': 12, 'MLC32-4408': 13, 'MLC41-4408': 14, 'MLC42-4408': 15, 'MLC51-4408': 16, 'MLC52-4408': 17,
            'MLC53-4408': 18, 'MLC54-4408': 19, 'MLC55-4408': 20, 'MLC61-4408': 21, 'MLC62-4408': 22, 'MLC63-4408': 23,
            'MLF11-4408': 24, 'MLF12-4408': 25, 'MLF13-4408': 26, 'MLF14-4408': 27, 'MLF21-4408': 28, 'MLF22-4408': 29,
            'MLF23-4408': 30, 'MLF24-4408': 31, 'MLF25-4408': 32, 'MLF31-4408': 33, 'MLF32-4408': 34, 'MLF33-4408': 35,
            'MLF34-4408': 36, 'MLF35-4408': 37, 'MLF41-4408': 38, 'MLF42-4408': 39, 'MLF43-4408': 40, 'MLF44-4408': 41,
            'MLF45-4408': 42, 'MLF46-4408': 43, 'MLF51-4408': 44, 'MLF52-4408': 45, 'MLF53-4408': 46, 'MLF54-4408': 47,
            'MLF55-4408': 48, 'MLF56-4408': 49, 'MLF61-4408': 50, 'MLF62-4408': 51, 'MLF63-4408': 52, 'MLF64-4408': 53,
            'MLF65-4408': 54, 'MLF66-4408': 55, 'MLF67-4408': 56, 'MLO11-4408': 57, 'MLO12-4408': 58, 'MLO13-4408': 59,
            'MLO14-4408': 60, 'MLO21-4408': 61, 'MLO22-4408': 62, 'MLO23-4408': 63, 'MLO24-4408': 64, 'MLO31-4408': 65,
            'MLO32-4408': 66, 'MLO33-4408': 67, 'MLO34-4408': 68, 'MLO41-4408': 69, 'MLO42-4408': 70, 'MLO43-4408': 71,
            'MLO44-4408': 72, 'MLO52-4408': 73, 'MLO53-4408': 74, 'MLP11-4408': 75, 'MLP12-4408': 76, 'MLP21-4408': 77,
            'MLP22-4408': 78, 'MLP23-4408': 79, 'MLP31-4408': 80, 'MLP32-4408': 81, 'MLP33-4408': 82, 'MLP34-4408': 83,
            'MLP35-4408': 84, 'MLP41-4408': 85, 'MLP42-4408': 86, 'MLP43-4408': 87, 'MLP44-4408': 88, 'MLP45-4408': 89,
            'MLP51-4408': 90, 'MLP52-4408': 91, 'MLP53-4408': 92, 'MLP54-4408': 93, 'MLP55-4408': 94, 'MLP56-4408': 95,
            'MLP57-4408': 96, 'MLT11-4408': 97, 'MLT12-4408': 98, 'MLT13-4408': 99, 'MLT14-4408': 100, 'MLT15-4408': 101,
            'MLT16-4408': 102, 'MLT21-4408': 103, 'MLT22-4408': 104, 'MLT23-4408': 105, 'MLT24-4408': 106, 'MLT25-4408': 107,
            'MLT26-4408': 108, 'MLT27-4408': 109, 'MLT31-4408': 110, 'MLT32-4408': 111, 'MLT33-4408': 112, 'MLT34-4408': 113,
            'MLT35-4408': 114, 'MLT37-4408': 115, 'MLT41-4408': 116, 'MLT42-4408': 117, 'MLT43-4408': 118, 'MLT44-4408': 119,
            'MLT45-4408': 120, 'MLT46-4408': 121, 'MLT47-4408': 122, 'MLT51-4408': 123, 'MLT52-4408': 124, 'MLT53-4408': 125,
            'MLT54-4408': 126, 'MLT55-4408': 127, 'MLT56-4408': 128, 'MLT57-4408': 129, 'MRC11-4408': 130, 'MRC12-4408': 131,
            'MRC13-4408': 132, 'MRC14-4408': 133, 'MRC15-4408': 134, 'MRC16-4408': 135, 'MRC17-4408': 136, 'MRC21-4408': 137,
            'MRC22-4408': 138, 'MRC23-4408': 139, 'MRC24-4408': 140, 'MRC25-4408': 141, 'MRC31-4408': 142, 'MRC32-4408': 143,
            'MRC41-4408': 144, 'MRC42-4408': 145, 'MRC51-4408': 146, 'MRC52-4408': 147, 'MRC53-4408': 148, 'MRC54-4408': 149,
            'MRC55-4408': 150, 'MRC61-4408': 151, 'MRC62-4408': 152, 'MRC63-4408': 153, 'MRF11-4408': 154, 'MRF12-4408': 155,
            'MRF13-4408': 156, 'MRF14-4408': 157, 'MRF21-4408': 158, 'MRF22-4408': 159, 'MRF23-4408': 160, 'MRF24-4408': 161,
            'MRF25-4408': 162, 'MRF31-4408': 163, 'MRF32-4408': 164, 'MRF33-4408': 165, 'MRF34-4408': 166, 'MRF35-4408': 167,
            'MRF41-4408': 168, 'MRF42-4408': 169, 'MRF43-4408': 170, 'MRF44-4408': 171, 'MRF45-4408': 172, 'MRF46-4408': 173,
            'MRF51-4408': 174, 'MRF52-4408': 175, 'MRF53-4408': 176, 'MRF54-4408': 177, 'MRF55-4408': 178, 'MRF56-4408': 179,
            'MRF61-4408': 180, 'MRF62-4408': 181, 'MRF63-4408': 182, 'MRF64-4408': 183, 'MRF65-4408': 184, 'MRF66-4408': 185,
            'MRF67-4408': 186, 'MRO11-4408': 187, 'MRO12-4408': 188, 'MRO13-4408': 189, 'MRO14-4408': 190, 'MRO21-4408': 191,
            'MRO22-4408': 192, 'MRO23-4408': 193, 'MRO24-4408': 194, 'MRO31-4408': 195, 'MRO32-4408': 196, 'MRO33-4408': 197,
            'MRO34-4408': 198, 'MRO41-4408': 199, 'MRO42-4408': 200, 'MRO43-4408': 201, 'MRO44-4408': 202, 'MRO51-4408': 203,
            'MRO52-4408': 204, 'MRO53-4408': 205, 'MRP11-4408': 206, 'MRP12-4408': 207, 'MRP21-4408': 208, 'MRP22-4408': 209,
            'MRP23-4408': 210, 'MRP31-4408': 211, 'MRP32-4408': 212, 'MRP33-4408': 213, 'MRP34-4408': 214, 'MRP35-4408': 215,
            'MRP41-4408': 216, 'MRP42-4408': 217, 'MRP43-4408': 218, 'MRP44-4408': 219, 'MRP45-4408': 220, 'MRP51-4408': 221,
            'MRP52-4408': 222, 'MRP53-4408': 223, 'MRP54-4408': 224, 'MRP55-4408': 225, 'MRP56-4408': 226, 'MRP57-4408': 227,
            'MRT11-4408': 228, 'MRT12-4408': 229, 'MRT13-4408': 230, 'MRT14-4408': 231, 'MRT15-4408': 232, 'MRT16-4408': 233,
            'MRT21-4408': 234, 'MRT22-4408': 235, 'MRT23-4408': 236, 'MRT24-4408': 237, 'MRT25-4408': 238, 'MRT26-4408': 239,
            'MRT27-4408': 240, 'MRT31-4408': 241, 'MRT32-4408': 242, 'MRT33-4408': 243, 'MRT34-4408': 244, 'MRT35-4408': 245,
            'MRT36-4408': 246, 'MRT37-4408': 247, 'MRT41-4408': 248, 'MRT42-4408': 249, 'MRT43-4408': 250, 'MRT44-4408': 251,
            'MRT45-4408': 252, 'MRT46-4408': 253, 'MRT47-4408': 254, 'MRT51-4408': 255, 'MRT52-4408': 256, 'MRT53-4408': 257,
            'MRT54-4408': 258, 'MRT55-4408': 259, 'MRT56-4408': 260, 'MRT57-4408': 261, 'MZC01-4408': 262, 'MZC02-4408': 263,
            'MZC03-4408': 264, 'MZC04-4408': 265, 'MZF01-4408': 266, 'MZF02-4408': 267, 'MZF03-4408': 268, 'MZO01-4408': 269,
            'MZO02-4408': 270, 'MZO03-4408': 271, 'MZP01-4408': 272}
}


def get_brain_mapping(raw_info):
    """Generate brain mapping based on raw information."""
    # Divide the channels into regions
    idx = _divide_to_regions(raw_info)

    # Create the BRAIN_MAPPING dictionary
    brain_mapping = {}
    for region, channel_indices in idx.items():
        # Get the actual channel names
        channel_names = [raw_info.ch_names[i] for i in channel_indices if i < len(raw_info.ch_names)]
        brain_mapping[region] = channel_names

    return brain_mapping


def get_chan_mapping(raw_info):
    """Generate channel mapping based on raw information."""
    # Create the CHAN_MAPPING dictionary
    chan_mapping = {name: idx for idx, name in enumerate(raw_info.ch_names)}
    return chan_mapping

def create_channel_index_mapping():
    chan_mapping = {}
    raw_file = "/data/liaopan/deep_decoding/MEG-to-Speech/datasets/ChineseSentences/raw/sub-01/ses-01_tsss.fif" #neuromag
    raw_file = "/data/liaopan/datasets/WAND_Extracted/sub-00395/ses-01/meg/sub-00395_ses-01_task-visual.ds"
    raw = mne.io.read_raw(raw_file)
    # raw.pick_types(meg=True)
    raw.pick_types(meg='mag')
    for channel in raw.ch_names:
        chan_mapping[channel] = raw.ch_names.index(channel)
    return chan_mapping


def get_brain_name(ch_name, device='neuromag'):
    """
    Get the brain region corresponding to a given channel name.

    Parameters
    ----------
    ch_name : str
        The channel name to look up (e.g., 'MEG0121').
    device : str, optional
        The device type to use for the mapping (default is 'neuromag').

    Returns
    -------
    str
        The name of the brain region corresponding to the channel.
        If the channel name is not found, returns 'other'.

    Examples
    --------
    >>> get_brain_name('MEG0121', 'neuromag')
    'Left-frontal'

    >>> get_brain_name('MEGXYZ', 'neuromag')
    'other'
    """
    # Access the device mapping in BRAIN_MAPPING
    device_mapping = BRAIN_MAPPING.get(device, {})

    # Iterate through each region and check if the channel name exists
    for region, channels in device_mapping.items():
        if ch_name in channels:
            return region

    # Return 'other' if no match is found
    return 'other'


def get_selection(name, device='neuromag'):
    """
    Get a list of channels associated with a given brain region for a specific device.

    Parameters
    ----------
    name : str
        The brain region name to look up (e.g., 'Left-frontal').
    device : str, optional
        The device type to use for the mapping (default is 'neuromag').

    Returns
    -------
    list of str
        A list of channel names associated with the brain region for the specified device.

    Examples
    --------
    >>> get_selection('Left-frontal', 'neuromag')
    ['MEG0121', 'MEG0122', 'MEG0123', ...]

    >>> get_selection('Right-temporal', 'ctf')
    []
    """
    selected_channels = []

    # Access the device mapping in BRAIN_MAPPING
    device_mapping = BRAIN_MAPPING.get(device, {})

    # Check if the brain region exists in the device mapping
    selected_channels = device_mapping.get(name, [])

    return selected_channels


if __name__ == "__main__":
    # brain_area = ['Vertex',
    #               'Left-temporal', 'Right-temporal',
    #               'Left-parietal', 'Right-parietal',
    #               'Left-occipital', 'Right-occipital',
    #               'Left-frontal', 'Right-frontal']
    #
    # for i in brain_area:
    #     print(f"brain-{i}", mne.read_vectorview_selection(i))

    # print(get_selection('Left-frontal'))
    # print(get_brain_name(ch_name='MEG111',device='neuromag'))
    # print(create_channel_index_mapping())

    raw = mne.preprocessing.read_ica("/data/liaopan/megprep_demo/wand_dataset/derivatives/preprocessed/ica_report/sub-00395_ses-01_task-visual/sub-00395_ses-01_task-visual_preproc-raw_ica.fif")

    # Get BRAIN_MAPPING and CHAN_MAPPING
    brain_mapping = get_brain_mapping(raw.info)
    chan_mapping = get_chan_mapping(raw.info)

    print("raw.info:",raw.info)

    # Print the results
    print("BRAIN_MAPPING:", brain_mapping)
    print("CHAN_MAPPING:", chan_mapping)

    print(BRAIN_MAPPING['ctf'])