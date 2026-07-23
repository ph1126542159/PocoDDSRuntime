//
// UnitsOfMeasureService.cpp
//
// Library: IoT/UnitsOfMeasure
// Package: UnitsOfMeasure
// Module:  UnitsOfMeasureService
//
// Copyright (c) 2018, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "IoT/UnitsOfMeasure/UnitsOfMeasureService.h"


namespace IoT {
namespace UnitsOfMeasure {


UnitsOfMeasureService::UnitsOfMeasureService()
{
}


UnitsOfMeasureService::~UnitsOfMeasureService()
{
}


const std::type_info& UnitsOfMeasureService::type() const
{
	return typeid(UnitsOfMeasureService);
}


bool UnitsOfMeasureService::isA(const std::type_info& other) const
{
	return std::string(other.name()) == typeid(UnitsOfMeasureService).name() ||
		Poco::OSP::Service::isA(other);
}


} } // namespace IoT::UnitsOfMeasure
