/**
 * The shared kit on one page, every part in every state, for the side-by-side look (standing rule R3: eyes before "done"). Built only
 * from kit parts (it is the first entry of KIT_PAGES). Served by the practice server at /kit.html; never part of the built app.
 */
import { useState } from "react";

import { KIT_WORDS, type KitTone } from "./chipWords";
import { Button, ButtonLink, Card, Notice, PageHeader, Row, SectionTitle, SelectField, Small, Stack, StatusChip, Table, TextField, Tile, Tiles } from "./Kit";

const TONES: KitTone[] = ["done", "check", "late", "info", "plain"];

export function KitPreview() {
  const [opened, setOpened] = useState<string | null>(null);
  return (
    <main id="main" className="kit-preview">
      <PageHeader title="Shared kit" lead="Every page builds its parts from these, and styles none of them itself."
        actions={<><Button variant="primary">Approve the reply</Button><Button>Send back with a note</Button></>} />
      <Small>Updated 1 min ago</Small>
      <SectionTitle>Tiles</SectionTitle>
      <Tiles label="Waiting for a decision">
        <Tile name="Document reviews" number={16} label="waiting for you" done={12} late={0} lateWords="no due dates set" onOpen={() => setOpened("reviews")} />
        <Tile name="Queries and CFCs" number={34} label="waiting for you" done={3} late={2} onOpen={() => setOpened("queries")} />
        <Tile name="Deliverables" number={null} label="waiting for you" done={null} lateWords="no due dates set" onOpen={() => setOpened("deliverables")} />
      </Tiles>
      {opened ? <Small>Would open: {opened}</Small> : null}
      <SectionTitle>Buttons</SectionTitle>
      <Card>
        <Stack gap={3}>
          <Row><Button variant="primary">Primary</Button><Button>Secondary</Button><Button variant="primary" disabled>Primary, off</Button><Button disabled>Secondary, off</Button></Row>
          <Row><Button variant="primary" size="sm">Small primary</Button><Button size="sm">Small secondary</Button><ButtonLink href="#kit">A link as a button</ButtonLink></Row>
        </Stack>
      </Card>
      <SectionTitle>Status chips: a fixed colour per word</SectionTitle>
      <Card>
        <Stack gap={3}>
          {TONES.map((tone) => <Row key={tone} label={`${tone} words`}>{KIT_WORDS[tone].map((w) => <StatusChip key={w} word={w[0].toUpperCase() + w.slice(1)} />)}</Row>)}
          <Row><StatusChip word="No query number" why="The subject has no full query number, so a person must check which query this is." /></Row>
        </Stack>
      </Card>
      <SectionTitle>Card, table and form</SectionTitle>
      <Card title="A card with a title" labelledBy="kit-card-title">
        <Stack gap={4}>
        <Table caption="Example rows" columns={["Query", "Status", "Who has it", "Due"]} rows={[
          { key: "1", cells: ["CFC-7 Invented coating question", <StatusChip key="s" word="Waiting for approval" />, "Nobody assigned", "3 Dec 2026"] },
          { key: "2", cells: ["TQ-00012 Invented valve question", <StatusChip key="s" word="In progress" />, "Invented Engineer", "no due date"] },
          { key: "3", cells: ["Please advise", <StatusChip key="s" word="Approved" />, "Invented Engineer", "no due date"] },
        ]} />
          <TextField id="kit-name" label="Contractor" placeholder="not named in the subject" hint="Saved for this query only." />
          <SelectField id="kit-order" label="Order"><option>Newest first</option><option>Oldest first</option></SelectField>
        </Stack>
      </Card>
      <SectionTitle>Notice boxes</SectionTitle>
      <Stack gap={3}>
        <Notice tone="info" title="A fact to know">Market prices are example figures only, until you search for real ones.</Notice>
        <Notice tone="warn" title="Check this">Some people will find nothing yet: their documents are still being read.</Notice>
        <Notice tone="problem" title="Something went wrong">The mailbox could not be read. Connect it again.</Notice>
      </Stack>
    </main>
  );
}
