#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Loader voor Baarn Raadsinformatie Server.
Laadt agent definities uit YAML bestanden.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from shared.logging_config import get_logger

logger = get_logger('agents')


@dataclass
class AgentArgument:
    """Argument voor een agent prompt."""
    name: str
    description: str
    required: bool = False


@dataclass
class AgentPrompt:
    """MCP Prompt configuratie."""
    description: str
    arguments: List[AgentArgument] = field(default_factory=list)


@dataclass
class AgentDefinition:
    """Volledige agent definitie."""
    name: str
    version: str
    description: str
    category: str
    prompt: AgentPrompt
    system_prompt: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, str]] = field(default_factory=list)
    related_agents: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, data: Dict) -> 'AgentDefinition':
        """Create AgentDefinition from parsed YAML data."""
        # Parse prompt arguments
        prompt_data = data.get('prompt', {})
        arguments = [
            AgentArgument(
                name=arg.get('name', ''),
                description=arg.get('description', ''),
                required=arg.get('required', False)
            )
            for arg in prompt_data.get('arguments', [])
        ]

        prompt = AgentPrompt(
            description=prompt_data.get('description', ''),
            arguments=arguments
        )

        return cls(
            name=data.get('name', 'unknown'),
            version=data.get('version', '1.0'),
            description=data.get('description', ''),
            category=data.get('category', 'general'),
            prompt=prompt,
            system_prompt=data.get('system_prompt', ''),
            metadata=data.get('metadata', {}),
            examples=data.get('examples', []),
            related_agents=data.get('related_agents', [])
        )

    def to_mcp_prompt(self) -> Dict:
        """Convert to MCP prompt format."""
        return {
            'name': self.name,
            'description': self.prompt.description,
            'arguments': [
                {
                    'name': arg.name,
                    'description': arg.description,
                    'required': arg.required
                }
                for arg in self.prompt.arguments
            ]
        }

    def get_system_message(self, **kwargs) -> str:
        """Get the system message for this agent, with optional variable substitution."""
        message = self.system_prompt
        for key, value in kwargs.items():
            message = message.replace(f'{{{key}}}', str(value))
        return message


class AgentLoader:
    """Laadt en beheert agent definities."""

    def __init__(self, agents_dir: Path = None):
        """Initialize agent loader.

        Args:
            agents_dir: Directory met agent YAML bestanden
        """
        if agents_dir is None:
            agents_dir = Path(__file__).parent
        self.agents_dir = Path(agents_dir)
        self._agents: Dict[str, AgentDefinition] = {}
        self._loaded = False

    def load_agents(self) -> Dict[str, AgentDefinition]:
        """Load all agent definitions from YAML files."""
        if self._loaded:
            return self._agents

        self._agents = {}

        if not self.agents_dir.exists():
            logger.warning(f'Agents directory not found: {self.agents_dir}')
            return self._agents

        # Load all YAML files
        for yaml_file in self.agents_dir.glob('*.yaml'):
            try:
                agent = self._load_agent_file(yaml_file)
                if agent:
                    self._agents[agent.name] = agent
                    logger.debug(f'Loaded agent: {agent.name}')
            except Exception as e:
                logger.error(f'Failed to load agent from {yaml_file}: {e}')

        self._loaded = True
        logger.info(f'Loaded {len(self._agents)} agents')
        return self._agents

    def _load_agent_file(self, file_path: Path) -> Optional[AgentDefinition]:
        """Load a single agent definition file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            return AgentDefinition.from_yaml(data)

        except yaml.YAMLError as e:
            logger.error(f'YAML parse error in {file_path}: {e}')
            return None

    def get_agent(self, name: str) -> Optional[AgentDefinition]:
        """Get agent by name."""
        if not self._loaded:
            self.load_agents()
        return self._agents.get(name)

    def get_agents(self, category: str = None) -> List[AgentDefinition]:
        """Get all agents, optionally filtered by category."""
        if not self._loaded:
            self.load_agents()

        agents = list(self._agents.values())

        if category:
            agents = [a for a in agents if a.category == category]

        return agents

    def get_mcp_prompts(self) -> List[Dict]:
        """Get all agents as MCP prompts."""
        if not self._loaded:
            self.load_agents()

        return [agent.to_mcp_prompt() for agent in self._agents.values()]

    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        if not self._loaded:
            self.load_agents()

        return list(set(a.category for a in self._agents.values()))

    def reload(self):
        """Reload all agent definitions."""
        self._loaded = False
        self._agents = {}
        self.load_agents()


# Singleton instance
_loader_instance = None


def get_agent_loader() -> AgentLoader:
    """Get singleton agent loader instance."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = AgentLoader()
    return _loader_instance


def get_agent(name: str) -> Optional[AgentDefinition]:
    """Convenience function to get agent by name."""
    return get_agent_loader().get_agent(name)


def get_all_agents() -> List[AgentDefinition]:
    """Convenience function to get all agents."""
    return get_agent_loader().get_agents()


def get_mcp_prompts() -> List[Dict]:
    """Convenience function to get MCP prompts."""
    return get_agent_loader().get_mcp_prompts()


if __name__ == '__main__':
    # Test the loader
    loader = AgentLoader()
    agents = loader.load_agents()

    print(f"\nLoaded {len(agents)} agents:")
    print("-" * 50)

    for name, agent in agents.items():
        print(f"\n{agent.name} (v{agent.version})")
        print(f"  Category: {agent.category}")
        print(f"  Description: {agent.description}")
        print(f"  Arguments: {len(agent.prompt.arguments)}")
        if agent.related_agents:
            print(f"  Related: {', '.join(agent.related_agents)}")

    print("\n" + "=" * 50)
    print("Categories:", loader.get_categories())

    print("\n" + "=" * 50)
    print("MCP Prompts:")
    for prompt in loader.get_mcp_prompts():
        print(f"  - {prompt['name']}: {len(prompt['arguments'])} args")
