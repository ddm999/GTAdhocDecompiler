import argparse, re, subprocess
from xml.dom.expatbuilder import parseString

RE_ORIGINAL_FILE_NAME = r"Original File Name: ([^\n]*)"

RE_LEAVE = r"\| LEAVE:.*"
RE_INSTRUCTION = r"\d*\| *(\d*)\| *\d*\| *([^:\-\n]*)(?:[:\-] (.*))?"

RE_SETSTATE_VALUE = r"State=\w* \((\d)\)"

parser = argparse.ArgumentParser(
    description="Decompiles a disassembled Adhoc file."
)
parser.add_argument("input_file", help="File to decompile (.ad, .ad.diss)")
parser.add_argument("output_folder", nargs='?', help="Output location (folder, default is 'generated')")
out = parser.parse_args()
FILE = out.input_file
OUTFOLDER = out.output_folder or 'generated'

if FILE.endswith(".adc"):
    try:
        subprocess.run(
            ["GTAdhocTools.exe", FILE],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        print("==> When providing an .adc (or .ad) file, GTAdhocTools.exe must be on the $PATH or in cwd.")
        exit(1)
    FILE = FILE[:-4]+".ad.diss"


lines = []
with open(FILE, "r") as f:
    lines = f.readlines()

filesout = {}
curfilename = re.search(RE_ORIGINAL_FILE_NAME, lines[1]).group(1)
stringout = ""
linestack = []
curlineno = 0
multilinestack = False

arraycounter = 0

for line in lines:
    # any line with an instruction which is not a leave
    re_instr = re.search(RE_INSTRUCTION, line)
    if (line == "" or re.search(RE_LEAVE, line) is not None or re_instr is None):
        continue

    # if the next instruction is on a later line, add lines until we get there
    while int(re_instr.group(1)) > curlineno+1:
        for object in linestack:
            stringout += object
        stringout += "\n"
        if linestack != []:
            print(f"[W] Line stack for {curfilename}:L{curlineno} wasn't empty!")
            print(linestack)
            multilinestack = True
        else:
            multilinestack = False
        curlineno += 1


    match re_instr.group(2).strip(" \n"):
        case "SOURCE_FILE":
            filesout[curfilename] = stringout
            curlineno = 0
            stringout = ""
            curfilename = re_instr.group(3)
            if curfilename in filesout.keys():
                stringout = filesout[curfilename]
        case "IMPORT":
            importsplit = re_instr.group(3).split(",")
            modulepath = importsplit[0].strip()
            modulename = importsplit[1].split("=")[1].strip()
            if importsplit[2].strip() != "Unk3=nil":
                print("[E] IMPORT instruction with non-nil 3rd parameter!")
                exit(0)
            stringout += f"import {modulepath}::{modulename};"
        case "MODULE_DEFINE":
            modulename = re_instr.group(3).split(",")[-1]
            stringout += f"module {modulename} {{"
        case "CLASS_DEFINE":
            classsplit = re_instr.group(3).split("extends")
            classname = classsplit[0].strip(" ")
            extendsname = classsplit[1].split(",")[-1]
            stringout += f"class {classname} extends {extendsname} {{"
        case "ATTRIBUTE_DEFINE":
            attributename = re_instr.group(3)
            val = linestack.pop(-1)
            if val == "nil":
                stringout += f"attribute {attributename};"
            else:
                stringout += f"attribute {attributename}={val};"
        case "STATIC_DEFINE":
            staticname = re_instr.group(3)
            stringout += f"static {staticname};"
        case x if x == "FUNCTION_DEFINE" or x == "METHOD_DEFINE":
            functionsplit = re_instr.group(3).split("(")
            functionname = functionsplit[0]
            functionargs = functionsplit[1].strip(")").split(",")
            argcount = len(functionargs)
            argstring = ""
            for i in range(argcount):
                # no args causes an empty string in the list
                if functionargs[i] == "":
                    continue
                arg = functionargs[i].strip(' ')[:-3]
                val = linestack.pop(-(argcount-i))
                if val == "nil":
                    argstring += f"{arg}, "
                else:
                    argstring += f"{arg}={val}, "

            typename = "function" if x == "FUNCTION_DEFINE" else "method"
            stringout += f"{typename} {functionname}({argstring[:-2] if argstring else ''}) {{"
        case x if x == "FUNCTION_CONST" or x == "METHOD_CONST":
            functionargs = re_instr.group(3).strip("()").split(",")
            argcount = len(functionargs)
            argstring = ""
            for i in range(argcount):
                # no args causes an empty string in the list
                if functionargs[i] == "":
                    continue
                arg = functionargs[i].strip(' ')[:-3]
                val = linestack.pop(-(argcount-i))
                if val == "nil":
                    argstring += f"{arg}, "
                else:
                    argstring += f"{arg}={val}, "

            typename = "function" if x == "FUNCTION_CONST" else "method"
            stringout += f"{typename}({argstring[:-2] if argstring else ''}) {{"
        case "VARIABLE_EVAL":
            varname = re_instr.group(3).strip().split(',')[-2]
            linestack.append(varname)
        case "ATTRIBUTE_EVAL":
            varname = linestack.pop(-1)
            linestack.append(f"{varname}.{re_instr.group(3).strip().split(',')[-1]}")
        case "CALL":
            argcount = int(re_instr.group(3).split('=')[-1])
            if argcount >= len(linestack):
                for i in range(1 + argcount - len(linestack)):
                    linestack.append("<UNKNOWN_VALUE>")
            callstring = f"{linestack.pop(-(argcount+1))}("
            # iterate over args, pulling out of stack
            for i in range(argcount):
                arg = linestack.pop(-(argcount-i))
                callstring += f"{arg}, "
            # remove trailing comma (only if there were args)
            callstring = f"{callstring[:-2] if argcount > 0 else callstring})"
            linestack.append(callstring)
        case "STRING_CONST":
            val = re_instr.group(3)
            linestack.append(f'"{val}"')
        case "SYMBOL_CONST":
            val = re_instr.group(3)
            linestack.append(f'$"{val}"')
        case "BOOL_CONST":
            val = re_instr.group(3).lower()
            linestack.append(f"{val}")
        case "INT_CONST":
            val = re_instr.group(3).strip(" ").split(" ")[0]
            linestack.append(f"{val}")
        case "U_INT_CONST":
            val = re_instr.group(3).strip(" ").split(" ")[0]
            linestack.append(f"{val}u")
        case "FLOAT_CONST":
            val = re_instr.group(3).split("=")[-1]
            linestack.append(f"{val}f")
        case "NIL_CONST":
            linestack.append(f"nil")
        case "VOID_CONST":
            linestack.append("")
        case "ARRAY_CONST":
            arraycounter = int(re_instr.group(3)[1:-1])
            linestack.append("[")
        case "ARRAY_PUSH":
            val = linestack.pop(-1)
            currentarray = linestack.pop(-1) if len(linestack) > 0 else ""
            arraycounter -= 1
            if arraycounter == 0:
                linestack.append(f"{currentarray}{val}]")
            else:
                linestack.append(f"{currentarray}{val}, ")
        case "MAP_CONST":
            linestack.append("[")
        case "MAP_INSERT":
            val = linestack.pop(-1)
            key = linestack.pop(-1)
            currentmap = linestack.pop(-1)
            if multilinestack:
                currentmap = ""
            linestack.append(f"{currentmap}{key}: {val},")
        case "ELEMENT_EVAL":
            indexval = linestack.pop(-1)
            varname = linestack.pop(-1)
            linestack.append(f"{varname}[{indexval}]")
        case "ELEMENT_PUSH":
            indexval = linestack.pop(-1)
            varname = linestack.pop(-1)
            linestack.append(f"{varname}[{indexval}]")
        case "STRING_PUSH":
            itemcount = int(re_instr.group(3).split("=")[-1])
            if itemcount == 0:
                linestack.append(f'""')
            else:
                listout = f"<STRING_PUSH> ["
                for i in range(itemcount):
                    listout += f"{linestack.pop(-(itemcount-i))}, "
                listout = listout[:-2]+"]"
                linestack.append(listout)
        case "LIST_ASSIGN":
            listout = "["
            itemcount = int(re_instr.group(3).split(",")[0].split("=")[-1])
            for i in range(itemcount):
                listout += f"{linestack.pop(-(itemcount-i))}, "
            listout = listout[:-2]+"]"
            val = linestack.pop(-1)
            linestack.append(f"{listout} = {val}")
        case "BINARY_ASSIGN_OPERATOR":
            operator = re_instr.group(3).strip(" ").split(" ")[0]
            if operator == "__sub__":
                operator = "-"
            var1 = linestack.pop(-2)
            var2 = linestack.pop(-1)
            linestack.append(f"{var1} {operator}= {var2}")
        case "BINARY_OPERATOR":
            operator = re_instr.group(3).strip(" ").split(" ")[0]
            if operator == "__sub__":
                operator = "-"
            var1 = linestack.pop(-2)
            var2 = linestack.pop(-1)
            linestack.append(f"{var1} {operator} {var2}")
        case "UNARY_ASSIGN_OPERATOR":
            operator = re_instr.group(3).strip(" ").split(" ")[0]
            var = linestack.pop(-1)
            linestack.append(f"{operator.replace('@', var)}")
        case "UNARY_OPERATOR":
            operator = re_instr.group(3).strip(" ").split(" ")[0]
            var = linestack.pop(-1)
            linestack.append(f"{operator.replace('@', var) if '@' in operator else operator+var}")
        case "LOGICAL_OR":
            expr = linestack.pop(-1)
            stringout += f"<condition='{expr}' || OR>"
        case "LOGICAL_AND":
            expr = linestack.pop(-1)
            stringout += f"<condition='{expr}' && AND>"
        case "POP":
            expr = linestack.pop(-1)
            stringout += f"{expr};"
        case "ASSIGN_POP":
            varname = linestack.pop(-1)
            val = "<MISSING_VALUE>"
            if len(linestack) > 0:
                val = linestack.pop(-1)
            stringout += f"{varname} = {val};"
        case "ASSIGN":
            varname = linestack.pop(-1)
            val = "<MISSING_VALUE>"
            if len(linestack) > 0:
                val = linestack.pop(-1)
            linestack.append(f"{varname} = {val}")
        case "VARIABLE_PUSH":
            varsplit = re_instr.group(3).split(',')
            if len(linestack) == 0:
                # weird case, used with binary assign operators
                # variable must've been declared before
                linestack.append(f"{varsplit[-2]}")
                pass
            else:
                if len(varsplit) == 2:
                    # local variable
                    linestack.append(f"{varsplit[0]}")
                else:
                    # static variable
                    linestack.append(f"{varsplit[-2]}")
        case "ATTRIBUTE_PUSH":
            varname = linestack.pop(-1)
            linestack.append(f"{varname}.{re_instr.group(3)}")
        case "JUMP_IF_FALSE":
            condition = linestack.pop(-1)
            stringout += f"<JUMP_IF_FALSE condition='{condition}'>"
        case "JUMP_IF_TRUE":
            condition = linestack.pop(-1)
            stringout += f"<JUMP_IF_TRUE condition='{condition}'>"
        case "JUMP":
            stringout += f"<JUMP>"
        case "SET_STATE":
            state = int(re.search(RE_SETSTATE_VALUE, re_instr.group(3)).group(1))
            if state == 1:
                # return
                retval = linestack.pop(-1)
                stringout += f"return{'' if retval == '' else ' '+retval};"
            elif state == 0:
                stringout += f"<EXIT {re_instr.group(3).split('[EXIT ')[-1].strip('] ')}>"
        case "OBJECT_SELECTOR":
            two = linestack.pop(-1)
            one = linestack.pop(-1)
            linestack.append(f"object_selector({one}, {two})")
        case "EVAL":
            stringout += "<EVAL>"
        case _:
            print("=========================")
            print(stringout)
            print("=========================")
            print(f"UNKNOWN INSTRUCTION: {re_instr.group(2)}")
            exit(0)

filesout[curfilename] = stringout

import os
for filename in filesout.keys():
    try:
        os.makedirs(os.path.dirname(f"{OUTFOLDER}/{filename}"))
    except FileExistsError:
        pass

    with open(f"{OUTFOLDER}/{filename}comp", "w") as f:
        f.write(filesout[filename])