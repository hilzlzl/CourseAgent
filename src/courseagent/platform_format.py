"""Presentation at the platform boundary; never change answers or judge inputs."""
import re


def option_texts(options):
    """Remove a complete, ordered label sequence, not leading variable names."""
    stripped=[]
    for i,value in enumerate(options):
        label=chr(65+i)
        if re.match(r'^\s*'+label+r'\s+[+\-*/=<>]\s*[A-Za-z]',value):return list(options)
        match=re.match(r'^\s*(?:'+label+r'\s*[.．、:：)）]\s*|[（(]\s*'+label+r'\s*[)）]\s*|'+label+r'\s+)(\S[\s\S]*)$',value)
        if not match:return list(options)
        stripped.append(match[1])
    return stripped


def markdown_literal(text):
    # Escape punctuation instead of allowing scraped operators/JSON to become
    # emphasis, links, HTML or headings. Do not apply inside code fences.
    # Educoder recognizes \(…\) and \[…\] as TeX before Markdown
    # unescaping. Parentheses need no Markdown escape; entities keep literal
    # brackets, dollar signs and backslashes out of the math parser entirely.
    entities={'\\':'&#92;','[':'&#91;',']':'&#93;','$':'&#36;'}
    return ''.join(entities.get(c,'\\'+c if c in '`*_{}#+-.!|><=~' else c) for c in text)


def native_literal_delimiters(text):
    """Migrate our older HTML-to-Markdown escapes, leaving code untouched.

    Only use for native_structured_question descriptions, whose prose was
    escaped by markdown_literal, never for arbitrary authored TeX Markdown.
    """
    pattern=r'(?P<fence>^ {0,3}(?P<ticks>`{3,}|~{3,})[^\n]*\n[\s\S]*?^ {0,3}(?P=ticks)[ \t]*$)|(?P<inline>(?P<tick>`+)[^`\n]*(?P=tick))|(?P<escape>\\[\s\S])'
    entities={'(': '&#40;', ')': '&#41;', '[': '&#91;', ']': '&#93;'}
    def replace(match):
        value=match[0]
        return entities.get(value[1],value) if match.lastgroup=='escape' else value
    return re.sub(pattern,replace,text,flags=re.M)


def code_block(text):
    fence='`'*max(3,max((len(m[0])+1 for m in re.finditer(r'`+',text)),default=3))
    return fence+'text\n'+text+'\n'+fence


def plain_sample_blocks(text):
    """Render data as plain preformatted text; Educoder numbers fenced code."""
    from html import escape
    pattern=r'^ {0,3}(`{3,}|~{3,})text[ \t]*\n([\s\S]*?)\n {0,3}\1[ \t]*$'
    return re.sub(pattern,lambda m:'<pre class="sample-io">'+escape(m[2],quote=False)+'</pre>',text,flags=re.M)
