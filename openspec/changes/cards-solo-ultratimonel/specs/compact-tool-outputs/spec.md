# Delta for compact-tool-outputs

## ADDED Requirements

### Requirement: Compact Output by Default

`end_turn`, `mission_list`, and all read/list tools MUST emit compact output by default. Compact output MUST include only essential fields: identifiers, titles, and state. Compact output MUST NOT include raw `result_data` or full unfiltered payloads.

#### Scenario: end_turn returns compact output

- GIVEN a completed turn
- WHEN `end_turn` is called
- THEN the response contains only essential identifiers, titles, and state
- AND the response does not include raw `result_data`
- AND the response size stays bounded and small

#### Scenario: mission_list returns compact output

- GIVEN multiple missions exist
- WHEN `mission_list` is called
- THEN each mission is represented by its identifier, title, and state
- AND full mission descriptions are not included by default

#### Scenario: Read and list tools return compact output

- GIVEN a read or list tool is invoked
- WHEN it returns results
- THEN it emits essential fields only
- AND it omits raw `result_data`

### Requirement: No Global Verbose Flag

The server MUST NOT introduce a global `verbose` flag in this change. Compact output MUST be the default and MUST NOT depend on a global toggle.

#### Scenario: No global verbose toggle

- GIVEN the MCP tool surface
- WHEN the tool parameters are enumerated
- THEN no global `verbose` parameter exists
- AND compact output is the default for `end_turn`, `mission_list`, and read/list tools
