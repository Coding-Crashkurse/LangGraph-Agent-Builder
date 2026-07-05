import { Plus, Trash2 } from "lucide-react";

import type { AgentCardSpec, AgentSkillSpec } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { SchemaForm } from "./forms/SchemaForm";

const TAGS_SCHEMA = { type: "array", items: { type: "string" } } as const;

export function AgentCardEditor({
  value,
  onChange,
  flowName,
}: {
  value: AgentCardSpec;
  onChange: (value: AgentCardSpec) => void;
  flowName: string;
}) {
  const setSkill = (index: number, skill: AgentSkillSpec) => {
    const skills = value.skills.slice();
    skills[index] = skill;
    onChange({ ...value, skills });
  };

  return (
    <div className="space-y-3.5">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Agent name</Label>
          <Input
            value={value.name}
            placeholder={flowName}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
          />
        </div>
        <div>
          <Label>Provider organization</Label>
          <Input
            value={value.provider_organization}
            onChange={(e) => onChange({ ...value, provider_organization: e.target.value })}
          />
        </div>
      </div>
      <div>
        <Label>Description</Label>
        <Textarea
          value={value.description}
          rows={2}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Input modes</Label>
          <SchemaForm
            schema={{ properties: { modes: { ...TAGS_SCHEMA } } }}
            value={{ modes: value.default_input_modes }}
            onChange={(v) =>
              onChange({ ...value, default_input_modes: (v.modes as string[]) ?? [] })
            }
          />
        </div>
        <div>
          <Label>Output modes</Label>
          <SchemaForm
            schema={{ properties: { modes: { ...TAGS_SCHEMA } } }}
            value={{ modes: value.default_output_modes }}
            onChange={(v) =>
              onChange({ ...value, default_output_modes: (v.modes as string[]) ?? [] })
            }
          />
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <Label className="mb-0">Skills</Label>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              onChange({
                ...value,
                skills: [
                  ...value.skills,
                  {
                    id: `skill-${value.skills.length + 1}`,
                    name: "",
                    description: "",
                    tags: [],
                    examples: [],
                  },
                ],
              })
            }
          >
            <Plus className="h-3 w-3" /> Add skill
          </Button>
        </div>
        <div className="space-y-2">
          {value.skills.map((skill, index) => (
            <div key={index} className="rounded-lg border border-surface-700 bg-surface-850 p-3">
              <div className="grid grid-cols-2 gap-2">
                <Input
                  value={skill.id}
                  placeholder="id"
                  className="font-mono text-xs"
                  onChange={(e) => setSkill(index, { ...skill, id: e.target.value })}
                />
                <Input
                  value={skill.name}
                  placeholder="name"
                  onChange={(e) => setSkill(index, { ...skill, name: e.target.value })}
                />
              </div>
              <Textarea
                value={skill.description}
                rows={2}
                placeholder="description"
                className="mt-2"
                onChange={(e) => setSkill(index, { ...skill, description: e.target.value })}
              />
              <div className="mt-2 grid grid-cols-2 gap-2">
                <SchemaForm
                  schema={{
                    properties: { tags: { ...TAGS_SCHEMA, description: "tags" } },
                  }}
                  value={{ tags: skill.tags }}
                  onChange={(v) => setSkill(index, { ...skill, tags: (v.tags as string[]) ?? [] })}
                />
                <SchemaForm
                  schema={{
                    properties: { examples: { ...TAGS_SCHEMA, description: "examples" } },
                  }}
                  value={{ examples: skill.examples }}
                  onChange={(v) =>
                    setSkill(index, { ...skill, examples: (v.examples as string[]) ?? [] })
                  }
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="mt-1.5 text-red-400"
                onClick={() =>
                  onChange({ ...value, skills: value.skills.filter((_, i) => i !== index) })
                }
              >
                <Trash2 className="h-3 w-3" /> remove
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
