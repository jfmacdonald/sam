import sys
from statemachine import StateMachine

try:
    import regex as re
    re_supports_unicode_categories = True
except ImportError:
    import re
    re_supports_unicode_categories = False
    print(
        """Regular expression support for Unicode categories not available.
IDs starting with non-ASCII lowercase letters will not be recognized and
will be treated as titles. Please install Python regex module.

""", file=sys.stderr)


class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("NEW", self._new_file)
        self.stateMachine.add_state("SAM", self._sam)
        self.stateMachine.add_state("BLOCK", self._block)
        self.stateMachine.add_state("CODEBLOCK-START", self._codeblock_start)
        self.stateMachine.add_state("CODEBLOCK", self._codeblock)
        self.stateMachine.add_state("PARAGRAPH-START", self._paragraph_start)
        self.stateMachine.add_state("PARAGRAPH", self._paragraph)
        self.stateMachine.add_state("RECORD-START", self._record_start)
        self.stateMachine.add_state("RECORD", self._record)
        self.stateMachine.add_state("LIST-START", self._list_start)
        self.stateMachine.add_state("LIST", self._list_continue)
        self.stateMachine.add_state("NUM-LIST-START", self._num_list_start)
        self.stateMachine.add_state("NUM-LIST", self._num_list_continue)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")
        self.current_paragraph = None
        self.doc = DocStructure()
        self.source = None
        self.patterns = {
            'comment': re.compile(r'\s*#.*'),
            'block-start': re.compile(r'(\s*)([a-zA-Z0-9-_]+):(.*)'),
            'codeblock-start': re.compile(r'(\s*)```(.*)'),
            'codeblock-end': re.compile(r'(\s*)```\s*$'),
            'paragraph-start': re.compile(r'\w*'),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(r'\s*[a-zA-Z0-9-_]+::(.*)'),
            'list-item': re.compile(r'(\s*)\*\s(.*)'),
            'num-list-item': re.compile(r'(\s*)[0-9]+\.\s(.*)')
        }

    def parse(self, source):
        self.source = Source(source)
        self.stateMachine.run(self.source)

    def paragraph_start(self, line):
        self.current_paragraph = line.strip()

    def paragraph_append(self, line):
        self.current_paragraph += " " + line.strip()

    def pre_start(self, line):
        self.current_paragraph = line

    def pre_append(self, line):
        self.current_paragraph += line

    def _new_file(self, source):
        line = source.next_line
        if line[:4] == 'sam:':
            self.doc.new_root('sam', line[5:])
            return "SAM", source
        else:
            raise Exception("Not a SAM file!")

    def _block(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        local_indent = len(match.group(1))
        local_element = match.group(2).strip()
        local_content = match.group(3).strip()

        if local_content[:1] == ':':
            return "RECORD-START", source
        else:
            self.doc.new_block(local_element, local_content, local_indent)
            return "SAM", source

    def _codeblock_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        match = self.patterns['codeblock-start'].match(line)
        language = match.group(2).strip()
        self.doc.new_block('codeblock', language, local_indent)
        self.pre_start('')
        return "CODEBLOCK", source

    def _codeblock(self, source):
        line = source.next_line
        if self.patterns['codeblock-end'].match(line):
            self.doc.new_flow(Pre(self.current_paragraph))
            return "SAM", source
        else:
            self.pre_append(line)
            return "CODEBLOCK", source

    def _paragraph_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('p', '', local_indent)
        self.paragraph_start(line)
        return "PARAGRAPH", source

    def _paragraph(self, source):
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            para_parser = SamParaParser(self.current_paragraph, self.doc)
            para_parser.parse()
            return "SAM", source
        else:
            self.paragraph_append(line)
            return "PARAGRAPH", source

    def _list_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('ul', '', local_indent)
        match = self.patterns['list-item'].match(line)
        self.doc.new_block('li', str(match.group(2)).strip(), local_indent + 4)
        return "LIST", source

    def _list_continue(self, source):
        line = source.next_line
        local_indent = len(line) - len(line.lstrip(' '))
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['list-item'].match(line):
            match = self.patterns['list-item'].match(line)
            self.doc.new_block('li', str(match.group(2)).strip(), local_indent + 4)
            return "LIST", source
        else:
            raise Exception("Broken list at line " + str(source.currentLineNumber) + " " + source.filename)

    def _num_list_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('ul', '', local_indent)
        match = self.patterns['num-list-item'].match(line)
        self.doc.new_block('li', str(match.group(2)).strip(), local_indent + 4)
        return "NUM-LIST", source

    def _num_list_continue(self, source):
        line = source.next_line
        local_indent = len(line) - len(line.lstrip(' '))
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['num-list-item'].match(line):
            match = self.patterns['num-list-item'].match(line)
            self.doc.new_block('li', str(match.group(2)).strip(), local_indent + 4)
            return "NUM-LIST", source
        else:
            raise Exception("Broken num list at line " + str(source.currentLineNumber) + " " + source.filename)

    def _record_start(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        local_indent = len(match.group(1))
        local_element = match.group(2).strip()
        field_names = [x.strip() for x in self.patterns['record-start'].match(line).group(1).split(',')]
        self.doc.new_record_set(local_element, field_names, local_indent)
        return "RECORD", source

    def _record(self, source):
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        else:
            field_values = [x.strip() for x in line.split(',')]
            record = list(zip(self.doc.fields, field_values))
            self.doc.new_record(record)
            return "RECORD", source

    def _sam(self, source):
        line = source.next_line
        if line == "":
            return "END", source
        elif self.patterns['comment'].match(line):
            self.doc.new_comment(Comment('', line.strip()[1:]))
            return "SAM", source
        elif self.patterns['block-start'].match(line):
            return "BLOCK", source
        elif self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['codeblock-start'].match(line):
            return "CODEBLOCK-START", source
        elif self.patterns['list-item'].match(line):
            return "LIST-START", source
        elif self.patterns['num-list-item'].match(line):
            return "NUM-LIST-START", source
        elif self.patterns['paragraph-start'].match(line):
            return "PARAGRAPH-START", source
        else:
            raise Exception("I'm confused")

    def serialize(self, serialize_format):
        return self.doc.serialize(serialize_format)


class Block:
    def __init__(self, name='', content='', indent=0):
        self.name = name
        self.content = content
        self.indent = indent
        self.parent = None
        self.children = []

    def add_child(self, b):
        b.parent = self
        self.children.append(b)

    def add_sibling(self, b):
        b.parent = self.parent
        self.parent.children.append(b)

    def add_at_indent(self, b, indent):
        x = self.parent
        while x.indent >= indent:
            x = x.parent
        b.parent = x
        x.children.append(b)

    def __str__(self):
        return ''.join(self._output_block())

    def _output_block(self):
        yield " " * self.indent
        yield "[%s:'%s'" % (self.name, self.content)
        for x in self.children:
            yield "\n"
            yield str(x)
        yield "]"

    def serialize_xml(self):
        if self.children:
            if self.content:
                re_id = re.compile(r'^[\p{Ll}_]\S*$') if re_supports_unicode_categories else re.compile(r'[a-z_]\S*$')
                re_id_and_label = re.compile(r'^([\p{Ll}_]\S*)\s*["\'](.+)["\']$') if re_supports_unicode_categories else re.compile(r'^([a-z_]\S*)\s*["\'](.+)["\']$')
                if self.name == 'codeblock' and self.content:
                    yield '<{0} language="{1}">\n'.format(self.name, self.content)
                elif re.match(re_id, self.content) is not None:
                    yield '<{0}>\n<id>{1}</id>\n'.format(self.name, self.content)
                elif re.match(re_id_and_label, self.content) is not None:
                    match = re.match(re_id_and_label, self.content)
                    yield '<{0}>\n<id>{1}</id>\n<label>{2}</label>\n'.format(self.name, match.group(1), match.group(2))
                else:
                    yield "<{0}>\n".format(self.name)
                    yield "<title>{0}</title>\n".format(self.content)
            else:
                yield "<{0}>".format(self.name)
                if type(self.children[0]) is not Flow:
                    yield "\n"
            for x in self.children:
                yield from x.serialize_xml()
            yield "</{0}>\n".format(self.name)
        else:
            yield "<{0}>{1}</{0}>\n".format(self.name, self.content)


class Comment(Block):
    def __str__(self):
        return "[%s:'%s']" % ('#comment', self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content)


class Root(Block):
    def __init__(self, name='', content='', indent=-1):
        super().__init__(name, content, -1)

    def serialize_xml(self):
        yield '<?xml version="1.0" encoding="UTF-8"?>\n'
        for x in self.children:
            yield from x.serialize_xml()


class Flow(Block):
    def __init__(self, thing=None):
        self.flow = []
        if thing:
            self.append(thing)

    def __str__(self):
        return "[{0}]".format(''.join([str(x) for x in self.flow]))

    def append(self, thing):
        if not thing == '':
            self.flow.append(thing)

    def serialize_xml(self):
        for x in self.flow:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield self._escape_for_xml(x)

    def _escape_for_xml(self, s):
        t = dict(zip([ord('<'), ord('>'), ord('&')],['@lt;', '@gt;','@amp;']))
        return s.translate(t)


class Pre(Flow):
    def serialize_xml(self):
        yield "<![CDATA["
        for x in self.flow:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield x
        yield "]]>"


class Annotation:
    def __init__(self, annotation_type, text, canonical='', namespace=''):
        self.annotation_type = annotation_type
        self.text = text
        self.canonical = canonical
        self.namespace = namespace

    def __str__(self):
        return '[%s](%s "%s" (%s))' % (self.text, self.annotation_type, self.canonical, self.namespace)

    def serialize_xml(self):
        yield '<annotation type="{0}"'.format(self.annotation_type)
        if self.canonical:
            yield ' canonical="{0}"'.format(self.canonical)
        if self.namespace:
            yield ' namespace="{0}"'.format(self.namespace)
        yield '>{0}</annotation>'.format(self.text)


class Decoration(Block):
    def __init__(self, decoration_type, text):
        self.decoration_type = decoration_type
        self.text = text

    def __str__(self):
        return '[%s](%s)' % (self.text, self.decoration_type)

    def serialize_xml(self):
        yield '<decoration type="{1}">{0}</decoration>'.format(self.text, self.decoration_type)


class DocStructure:
    def __init__(self):
        self.doc = None
        self.fields = None
        self.current_record = None
        self.current_block = None

    def new_root(self, block_type, text):
        r = Root(block_type, text)
        self.doc = r
        self.current_block = r

    def new_block(self, block_type, text, indent):
        b = Block(block_type, text, indent)
        if self.doc is None:
            raise Exception('No root element found.')
        elif self.current_block.indent < indent:
            self.current_block.add_child(b)
        elif self.current_block.indent == indent:
            self.current_block.add_sibling(b)
        else:
            self.current_block.add_at_indent(b, indent)
        self.current_block = b
        # Useful lines for debugging the build of the tree
        # print(self.doc)
        # print('-----------------------------------------------------')

    def new_flow(self, flow):
        self.current_block.add_child(flow)

    def new_comment(self, comment):
        self.current_block.add_child(comment)


    def new_record_set(self, local_element, field_names, local_indent):
        self.current_record = {'local_element': local_element, 'local_indent': local_indent}
        self.fields = field_names

    def new_record(self, record):
        b = Block(self.current_record['local_element'], '', self.current_record['local_indent'])
        self.current_block.add_child(b)
        self.current_block = b
        for name, content in record:
            b = Block(name, content, self.current_block.indent + 4)
            self.current_block.add_child(b)
        self.current_block = self.current_block.parent

    def serialize(self, serialize_format):
        if serialize_format.upper() == 'XML':
            yield from self.doc.serialize_xml()
        else:
            raise Exception("Unknown serialization protocol{0}".format(serialize_format))


class Source:
    def __init__(self, file_to_parse):
        """

        :param file_to_parse: The filename of the source to parse.
        """
        self.file_to_parse = file_to_parse
        self.sourceFile = open(file_to_parse, encoding='utf-8')
        self.currentLine = None
        self.currentLineNumber = 0

    @property
    def next_line(self):
        self.currentLine = self.sourceFile.readline()
        self.currentLineNumber += 1
        return self.currentLine


class SamParaParser:
    def __init__(self, para, doc):
        self.doc = doc
        self.para = Para(para)
        self.stateMachine = StateMachine()
        self.stateMachine.add_state("PARA", self._para)
        self.stateMachine.add_state("ESCAPE", self._escape)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.add_state("ANNOTATION-START", self._annotation_start)
        self.stateMachine.add_state("BOLD-START", self._bold_start)
        self.stateMachine.add_state("ITALIC-START", self._italic_start)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile(r'\\'),
            'escaped-chars': re.compile(r'[\\\[\(\]_]'),
            'annotation': re.compile(r'\[([^\[]*?[^\\])\]\(([^\(]\w*?\s*[^\\"\'])(["\'](.*?)["\'])??\s*(\((\w+)\))?\)'),
            'bold': re.compile(r'\*(\S.+?\S)\*'),
            'italic': re.compile(r'_(\S.*?\S)_')
        }
        self.current_string = ''
        self.flow = Flow()

    def parse(self):
        self.stateMachine.run(self.para)

    def _para(self, para):
        try:
            char = para.next_char
        except IndexError:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.doc.new_flow(self.flow)
            return "END", para
        if char == '\\':
            return "ESCAPE", para
        elif char == '[':
            return "ANNOTATION-START", para
        elif char == "*":
            return "BOLD-START", para
        elif char == "_":
            return "ITALIC-START", para
        else:
            self.current_string += char
            return "PARA", para

    def _annotation_start(self, para):
        match = self.patterns['annotation'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            annotation_type = str(match.group(2)).strip()
            text = match.group(1)
            canonical = match.group(4) if match.group(4) is not None else None
            namespace = match.group(6) if match.group(6) is not None else None
            self.flow.append(Annotation(annotation_type, text, canonical, namespace))
            para.advance(len(match.group(0)) - 1)
            return "PARA", para
        else:
            self.current_string += '['
            return "PARA", para

    def _bold_start(self, para):
        match = self.patterns['bold'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('bold', match.group(1)))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '*'
        return "PARA", para

    def _italic_start(self, para):
        match = self.patterns['italic'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('italic', match.group(1)))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '_'
        return "PARA", para

    def _escape(self, para):
        char = para.next_char
        if self.patterns['escaped-chars'].match(char):
            self.current_string += char
        else:
            self.current_string += '\\' + char
        return "PARA", para


class Para:
    def __init__(self, para):
        self.para = para
        self.currentCharNumber = -1

    @property
    def next_char(self):
        self.currentCharNumber += 1
        return self.para[self.currentCharNumber]

    @property
    def current_char(self):
        return self.para[self.currentCharNumber]

    @property
    def rest_of_para(self):
        return self.para[self.currentCharNumber:]

    def advance(self, count):
        self.currentCharNumber += count


if __name__ == "__main__":
    samParser = SamParser()
    filename = sys.argv[-1]
    samParser.parse(filename)
    print("".join(samParser.serialize('xml')))