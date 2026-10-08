import json
import logging
import os
import shutil
import sys

from chgksuite.common import (
    DefaultArgs,
    DefaultNamespace,
    get_chgksuite_dir,
    get_lastdir,
    get_source_dirs,
    init_logger,
    log_wrap,
    read_text_file,
    set_lastdir,
)
from chgksuite.composer.chgksuite_parser import parse_4s
from chgksuite.composer.composer_common import (
    ext_to_game,
    make_filename,
    make_temp_directory,
)
from chgksuite.composer.db import DbExporter
from chgksuite.composer.docx import DocxExporter
from chgksuite.composer.lj import LjExporter
from chgksuite.composer.markdown import MarkdownExporter
from chgksuite.composer.openquiz import OpenquizExporter
from chgksuite.composer.pptx import PptxExporter
from chgksuite.composer.stats import StatsAdder
from chgksuite.composer.telegram import (
    TelegramExporter,
    stats_check_bypassed,
    structure_has_stats,
)
from chgksuite.composer.typst import TypstExporter


def files_have_stats(filenames, args=None):
    """Whether every file has the stats line; what `compose has_stats` prints."""
    if isinstance(filenames, str):
        filenames = [filenames]
    args = DefaultNamespace(args) if args is not None else None
    return all(
        structure_has_stats(parse_filepath(os.path.abspath(fn), args=args))
        for fn in filenames
    )


# The GUIs' question before a Telegram export of a pack without stats.
NO_STATS_TITLE = "Нет статистики"
NO_STATS_QUESTION = (
    "В пакете нет статистики взятий. Всё равно опубликовать в телеграм?"
)


def telegram_export_needs_confirmation(args):
    """Whether a GUI must ask before this run publishes a pack without stats.

    The GUIs ask whatever `stop_if_no_stats` says; the answer "yes" comes back
    as --allow_no_stats. A dry run publishes nothing, so it is not asked about.
    """
    if args.action != "compose" or args.filetype != "telegram":
        return False
    if getattr(args, "dry_run", False) or stats_check_bypassed(args):
        return False
    if not args.filename:
        return False
    return not files_have_stats(args.filename, args=args)


def confirm_telegram_export(parser, cmdline_call, display, ask):
    """The GUIs' check before a run: ask before publishing a pack without stats.

    ``ask(title, question)`` shows the toolkit's yes/no dialog, defaulting to
    no. Returns the command line and its display string to run, with
    --allow_no_stats added on "yes", or None when the user says no. If the pack
    cannot be checked, the user is asked as if it had no stats.
    """
    if cmdline_call[:2] != ["compose", "telegram"]:
        return cmdline_call, display
    try:
        needed = telegram_export_needs_confirmation(parser.parse_args(cmdline_call))
    except (Exception, SystemExit):
        logging.getLogger(__name__).exception("Could not check the pack for stats")
        needed = "--dry_run" not in cmdline_call
    if not needed:
        return cmdline_call, display
    if not ask(NO_STATS_TITLE, NO_STATS_QUESTION):
        return None
    return cmdline_call + ["--allow_no_stats"], display + " --allow_no_stats"


def gui_compose(args, logger=None):
    if args.filetype == "has_stats":
        if not args.filename:
            print("No file specified.")
            sys.exit(1)
        print(json.dumps({"has_stats": files_have_stats(args.filename, args=args)}))
        return

    sourcedir = get_source_dirs()[0]

    argsdict = vars(args)
    logger = logger or init_logger("composer", debug=args.debug)
    logger.debug(log_wrap(argsdict))

    ld = get_lastdir()
    if args.filename:
        if isinstance(args.filename, list):
            ld = os.path.dirname(os.path.abspath(args.filename[0]))
        else:
            ld = os.path.dirname(os.path.abspath(args.filename))
    set_lastdir(ld)
    if not args.filename:
        print("No file specified.")
        sys.exit(1)

    if isinstance(args.filename, list):
        if not args.merge:
            for fn in args.filename:
                targetdir = os.path.dirname(os.path.abspath(fn))
                filename = os.path.basename(os.path.abspath(fn))
                process_file_wrapper(filename, sourcedir, targetdir, args)
        else:
            targetdir = os.path.dirname(os.path.abspath(args.filename[0]))
            process_file_wrapper(args.filename, sourcedir, targetdir, args)
    else:
        targetdir = os.path.dirname(os.path.abspath(args.filename))
        filename = os.path.basename(os.path.abspath(args.filename))
        process_file_wrapper(filename, sourcedir, targetdir, args)


def process_file_wrapper(filename, sourcedir, targetdir, args):
    with make_temp_directory(dir=get_chgksuite_dir()) as tmp_dir:
        shutil.copy(args.docx_template, tmp_dir)
        process_file(filename, tmp_dir, targetdir, args)


def parse_filepath(filepath, args=None):
    args = args or DefaultArgs()
    game = getattr(args, "game", None) or ext_to_game(filepath)
    input_text = read_text_file(filepath)
    debug_dir = os.path.dirname(os.path.abspath(filepath))
    return parse_4s(
        input_text, randomize=args.randomize, debug=args.debug, debug_dir=debug_dir,
        game=game,
    )


def make_merged_filename(filelist):
    filelist = [os.path.splitext(os.path.basename(x))[0] for x in filelist]
    prefix = os.path.commonprefix(filelist)
    suffix = "_".join(x[len(prefix) :] for x in filelist)
    return prefix + suffix


def process_file(filename, tmp_dir, targetdir, args=None, logger=None):
    names = filename if isinstance(filename, list) else [filename]
    dir_kwargs = {
        "tmp_dir": tmp_dir,
        "targetdir": targetdir,
        "source_paths": [os.path.join(targetdir, x) for x in names],
    }
    logger = logger or init_logger("composer")

    if isinstance(filename, list):
        structure = []
        for x in filename:
            structure.extend(parse_filepath(os.path.join(targetdir, x), args=args))
        filename = make_merged_filename(filename)
    else:
        structure = parse_filepath(os.path.join(targetdir, filename), args=args)

    if args.debug:
        debug_fn = os.path.join(
            targetdir,
            make_filename(os.path.basename(filename), "dbg", args),
        )
        with open(debug_fn, "w", encoding="utf-8") as output_file:
            output_file.write(json.dumps(structure, indent=2, ensure_ascii=False))

    if not args.filetype:
        print("Filetype not specified.")
        sys.exit(1)
    if args.filetype == "docx":
        spoilers = args.spoilers
    else:
        spoilers = "off" if args.nospoilers else "on"
    logger.info(f"Exporting to {args.filetype}, spoilers are {spoilers}...\n")

    if args.filetype == "docx":
        if args.screen_mode == "off":
            addsuffix = ""
        elif args.screen_mode == "replace_all":
            addsuffix = "_screen"
        elif args.screen_mode in ["add_versions", "add_versions_columns"]:
            addsuffix = "_screen_versions"
        if args.spoilers != "off":
            addsuffix += "_spoilers"
        outfilename = os.path.join(
            targetdir, make_filename(filename, "docx", args, addsuffix=addsuffix)
        )
        exporter = DocxExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "pdf":
        addsuffix = "_mobile" if getattr(args, "device", None) == "mobile" else ""
        outfilename = os.path.join(
            tmp_dir, make_filename(filename, "typ", args, addsuffix=addsuffix)
        )
        exporter = TypstExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "lj":
        exporter = LjExporter(structure, args, dir_kwargs)
        exporter.export()

    if args.filetype == "base":
        exporter = DbExporter(structure, args, dir_kwargs)
        outfilename = os.path.join(targetdir, make_filename(filename, "txt", args))
        exporter.export(outfilename)

    if args.filetype in ("redditmd", "markdown"):
        exporter = MarkdownExporter(structure, args, dir_kwargs)
        outfilename = os.path.join(targetdir, make_filename(filename, "md", args))
        exporter.export(outfilename)

    if args.filetype == "pptx":
        outfilename = os.path.join(targetdir, make_filename(filename, "pptx", args))
        exporter = PptxExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "add_stats":
        outfilename = os.path.join(
            targetdir,
            make_filename(filename, "4s", args, addsuffix="_with_stats"),
        )
        exporter = StatsAdder(structure, args, dir_kwargs)
        exporter.export(outfilename)

    if args.filetype == "telegram":
        exporter = None
        try:
            exporter = TelegramExporter(structure, args, dir_kwargs)
            exporter.export()
        finally:
            if exporter is not None:
                exporter.close()

    if args.filetype == "openquiz":
        outfilename = os.path.join(targetdir, make_filename(filename, "json", args))
        exporter = OpenquizExporter(structure, args, dir_kwargs)
        exporter.export(outfilename)


def main():
    print("This program was not designed to run standalone.")


if __name__ == "__main__":
    main()
