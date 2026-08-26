//
// Configuration.cpp
//
// Library: OSP
// Package: PreferencesService
// Module:  Configuration
//
// Copyright (c) 2007-2014, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "Poco/OSP/Configuration.h"
#include "Poco/Exception.h"
#include "Poco/Util/MapConfiguration.h"


namespace Poco {
namespace OSP {

namespace
{
void copyProperties(const Poco::Util::AbstractConfiguration& configuration,
	const std::string& prefix, std::map<std::string, std::string>& values)
{
	Poco::Util::AbstractConfiguration::Keys keys;
	configuration.keys(prefix, keys);
	for (const auto& child: keys)
	{
		const std::string key = prefix.empty() ? child : prefix + "." + child;
		Poco::Util::AbstractConfiguration::Keys descendants;
		configuration.keys(key, descendants);
		if (descendants.empty()) values[key] = configuration.getRawString(key, "");
		else copyProperties(configuration, key, values);
	}
}
}


Configuration::Configuration(AbstractConfiguration* pConfig):
	_pConfig(pConfig)
{
	poco_check_ptr (pConfig);
	
	_pConfig->duplicate();
}


Configuration::~Configuration()
{
	_pConfig->release();
}


bool Configuration::getRaw(const std::string& key, std::string& value) const
{
	Poco::FastMutex::ScopedLock lock(_mutex);
	if (_pConfig->hasProperty(key))
	{
		value = _pConfig->getRawString(key);
		return true;
	}
	else return false;
}


void Configuration::setRaw(const std::string& key, const std::string& value)		
{
	throw Poco::InvalidAccessException("Cannot change configuration properties");
}


void Configuration::enumerate(const std::string& key, Keys& range) const
{
	Poco::FastMutex::ScopedLock lock(_mutex);
	_pConfig->keys(key, range);
}


void Configuration::removeRaw(const std::string& key)
{
	throw Poco::InvalidAccessException("Cannot change configuration properties");
}

void Configuration::setProperty(const std::string& key, const std::string& value)
{
	Poco::FastMutex::ScopedLock lock(_mutex);
	_pConfig->setString(key, value);
}


void Configuration::replaceProperties(const std::map<std::string, std::string>& values)
{
	Poco::Util::MapConfiguration* pReplacement = new Poco::Util::MapConfiguration;
	try
	{
		for (const auto& item: values) pReplacement->setString(item.first, item.second);
	}
	catch (...)
	{
		pReplacement->release();
		throw;
	}
	Poco::FastMutex::ScopedLock lock(_mutex);
	AbstractConfiguration* pPrevious = _pConfig;
	_pConfig = pReplacement;
	pPrevious->release();
}


std::map<std::string, std::string> Configuration::properties() const
{
	Poco::FastMutex::ScopedLock lock(_mutex);
	std::map<std::string, std::string> values;
	copyProperties(*_pConfig, "", values);
	return values;
}


} } // namespace Poco::OSP
