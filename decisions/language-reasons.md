# Reason declarations

A pack names why a value is not known with a reason code, and shows a sentence for it. The [language reference](../docs/rezono/v0.md), section 5, declares a reason once per pack with its label: `reason no_rate = "no monthly rate published yet"`. The reader already writes it to the module form as `{"reason": "no_rate", "text": "\"no monthly rate published yet\""}`. A pack in the existing notation writes the same sentence as `reason.no_rate = {{…}}` in its message file. This decision says how the declaration is published.

## Lowering

- **One sentence in the default language.** A reason declaration lowers to the message `reason.<code>` in the messages of the pack's `default_language`, with the label as its text, exactly as the line `reason.<code> = {{label}}` in `messages/<default_language>.mf2` gives it. The label is written in the language of the pack's names, so it is the sentence of that language. In the pattern, `\`, `{` and `}` of the label are escaped with a backslash, as MessageFormat 2 asks.
- **One source per sentence.** A code that a module declares and that the message file of the default language also gives is refused at the declaration: the two could differ, and nothing would say which one the pack means.
- **Other languages stay in their message files.** A sentence for the same code in another language is written in `messages/<lang>.mf2`, as for every other message ("labels and messages in another language than the written name" stay in their files).
- **The code is the key.** A state literal that names the label (`unknown "no monthly rate published yet"`) stores the code, as the reference says, so the published data and the proof never carry the label.

## Reading a label

A state literal in a module, such as the cell `unknown "no monthly rate published yet"` of a fact table, may name a reason by its label. The label must be the label of a reason that a module of the pack declares, compared as written. Any other label is R029, an error at the quoted label, and the module has no form. A state literal with a code (`unknown no_rate`) or a core code is not checked against the declarations here, since the reference lets a core code stand without one.

## Considered

- **A reason as a row of a fact table of the pack.** The sentence would then be data that a question can read, but a reason is part of the pack's meaning and changes with a release of the pack, like the other messages.
- **The declaration wins over the message file.** A silent precedence would hide a sentence that the author still sees in the file.
